"""
Security tests — the fixes from the review must stay enforced.
"""

import pytest
from fastapi.testclient import TestClient

from api import app
from gateway import reset_meter

client = TestClient(app)
_BODY = {"portfolio_returns": [0.01, -0.02, 0.015, -0.01] * 8}


def test_auth_secure_by_default_when_unset(monkeypatch):
    # With AUTH_STUB unset entirely, auth must be ENFORCED (not bypassed).
    reset_meter()
    monkeypatch.delenv("AUTH_STUB", raising=False)
    monkeypatch.delenv("MCP_API_KEYS", raising=False)
    r = client.post("/v1/tools/compute_var_cvar", json=_BODY)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_MISSING"


def test_demo_cap_ip_fallback_blocks_id_rotation():
    # Rotating the client-generated demo id must not grant unlimited runs:
    # the shared IP key hits the daily cap.
    from infra.demo_limits import DEMO_DAILY_RUN_LIMIT, consume_demo_run, reset

    assert DEMO_DAILY_RUN_LIMIT == 2
    reset()
    ip = "ip:203.0.113.7"
    assert consume_demo_run(["demo:A", ip])["allowed"] is True
    assert consume_demo_run(["demo:B", ip])["allowed"] is True
    # Third run from a fresh rotated id, same IP -> denied (IP at cap).
    assert consume_demo_run(["demo:C", ip])["allowed"] is False


def test_portal_key_authenticates_via_backend(monkeypatch):
    # A portal-issued key (not in MCP_API_KEYS) authenticates by verifying
    # against the backend store; an unknown key is rejected.
    reset_meter()
    monkeypatch.setenv("AUTH_STUB", "0")
    monkeypatch.delenv("MCP_API_KEYS", raising=False)
    import gateway.access as access
    monkeypatch.setattr(access, "_verify_via_backend", lambda k: "u_portal" if k == "portalkey" else None)
    ok = client.post("/v1/tools/compute_var_cvar", json=_BODY, headers={"Authorization": "Bearer portalkey"})
    assert ok.status_code == 200
    bad = client.post("/v1/tools/compute_var_cvar", json=_BODY, headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "AUTH_INVALID"


def test_demo_cap_per_id_still_enforced():
    from infra.demo_limits import consume_demo_run, reset

    reset()
    assert consume_demo_run(["demo:solo", "ip:198.51.100.1"])["allowed"] is True
    assert consume_demo_run(["demo:solo", "ip:198.51.100.2"])["allowed"] is True
    # Same id from a new IP -> denied (id at cap).
    assert consume_demo_run(["demo:solo", "ip:198.51.100.3"])["allowed"] is False
