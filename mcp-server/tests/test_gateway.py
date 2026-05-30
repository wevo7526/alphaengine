"""
T9 + T10 tests — per-client key auth + metering on the REST surface.

access.py reads env per request, so tests toggle AUTH_STUB / MCP_API_KEYS /
limits in-process. reset_meter() isolates counters between tests.
"""

import os

import pytest
from fastapi.testclient import TestClient

from api import app
from gateway import reset_meter

client = TestClient(app)
_BODY = {"portfolio_returns": [0.01, -0.02, 0.015, -0.01] * 8}  # 32 obs, valid


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    reset_meter()
    # Default: enforce auth for these tests (production-like).
    monkeypatch.setenv("AUTH_STUB", "0")
    monkeypatch.delenv("MCP_API_KEYS", raising=False)
    monkeypatch.setenv("SANDBOX_API_KEY", "ae_sandbox_public")
    yield
    reset_meter()


def test_stub_bypasses_auth(monkeypatch):
    monkeypatch.setenv("AUTH_STUB", "1")
    r = client.post("/v1/tools/compute_var_cvar", json=_BODY)
    assert r.status_code == 200


def test_missing_key_is_401():
    r = client.post("/v1/tools/compute_var_cvar", json=_BODY)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_MISSING"


def test_bad_key_is_401():
    r = client.post("/v1/tools/compute_var_cvar", json=_BODY, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_INVALID"


def test_sandbox_key_works():
    r = client.post(
        "/v1/tools/compute_var_cvar", json=_BODY,
        headers={"Authorization": "Bearer ae_sandbox_public"},
    )
    assert r.status_code == 200
    assert r.json()["determinism"] == "exact"


def test_paid_key_works(monkeypatch):
    monkeypatch.setenv("MCP_API_KEYS", "secret_abc:acme")
    r = client.post(
        "/v1/tools/compute_var_cvar", json=_BODY,
        headers={"Authorization": "Bearer secret_abc"},
    )
    assert r.status_code == 200


def test_quota_exceeded(monkeypatch):
    monkeypatch.setenv("SANDBOX_RATE_LIMIT", "2")
    h = {"Authorization": "Bearer ae_sandbox_public"}
    assert client.post("/v1/tools/compute_var_cvar", json=_BODY, headers=h).status_code == 200
    assert client.post("/v1/tools/compute_var_cvar", json=_BODY, headers=h).status_code == 200
    r = client.post("/v1/tools/compute_var_cvar", json=_BODY, headers=h)
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "QUOTA_EXCEEDED"


def test_usage_endpoint(monkeypatch):
    h = {"Authorization": "Bearer ae_sandbox_public"}
    client.post("/v1/tools/compute_var_cvar", json=_BODY, headers=h)
    r = client.get("/v1/usage", headers=h)
    assert r.status_code == 200
    assert r.json()["calls_in_window"] >= 1
