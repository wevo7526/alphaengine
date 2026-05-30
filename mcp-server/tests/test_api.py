"""
T6 tests — the deterministic REST surface. Uses FastAPI's TestClient (no
network). Asserts the versioned envelope, golden-consistent results through the
HTTP layer, typed errors with the right status, and the health/version routes.
"""

import numpy as np
from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_health():
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_version_lists_tools():
    body = client.get("/v1/version").json()
    assert "compute_var_cvar" in body["tools"]
    assert body["engine_version"].startswith("quant_core@")


def test_deflated_sharpe_through_http_is_golden():
    returns = np.random.default_rng(42).normal(0.0008, 0.018, 300).tolist()
    r = client.post("/v1/tools/deflated_sharpe", json={"returns": returns, "n_trials": 50})
    assert r.status_code == 200
    env = r.json()
    assert env["determinism"] == "exact"
    assert env["schema_version"] == "1.0.0"
    assert env["tool"] == "deflated_sharpe"
    # Golden-consistent through the wire (same as the quant_core golden test).
    assert env["result"]["deflated_sharpe"] == 0.0134
    assert env["result"]["verdict"] == "likely_noise"


def test_var_cvar_through_http():
    rng = np.random.default_rng(99)
    rets = (rng.normal(0.0005, 0.012, 500) - 0.0008 * (rng.random(500) > 0.95)).tolist()
    r = client.post("/v1/tools/compute_var_cvar", json={"portfolio_returns": rets})
    assert r.status_code == 200
    res = r.json()["result"]
    assert res["parametric"]["var_pct"] == 2.02
    assert res["cvar"]["cvar_pct"] == 2.57


def test_request_id_echoed():
    r = client.post(
        "/v1/tools/compute_var_cvar",
        json={"portfolio_returns": [0.01] * 30},
        headers={"X-Request-Id": "req_mine_123"},
    )
    assert r.json()["request_id"] == "req_mine_123"


def test_insufficient_observations_is_422_typed():
    r = client.post("/v1/tools/deflated_sharpe", json={"returns": [0.01] * 5, "n_trials": 10})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "INSUFFICIENT_OBSERVATIONS"
    assert err["request_id"].startswith("req_")


def test_unknown_tool_is_schema_invalid():
    r = client.post("/v1/tools/not_a_tool", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SCHEMA_INVALID"


def test_bad_json_is_typed():
    r = client.post(
        "/v1/tools/deflated_sharpe",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SCHEMA_INVALID"


def test_unknown_field_rejected():
    r = client.post("/v1/tools/deflated_sharpe", json={"returns": [0.01] * 10, "n_trials": 1, "x": 1})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SCHEMA_INVALID"
