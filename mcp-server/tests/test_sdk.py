"""
T11 tests — the Python SDK, run in-process against the real API app via an
injected TestClient (no network). Proves the client speaks the real contract:
golden-consistent results, typed errors, health/version.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from alphaengine import AlphaEngineError, Client
from api import app

ae = Client(session=TestClient(app))  # AUTH_STUB defaults on locally


def test_health_and_version():
    assert ae.health()["status"] == "ok"
    assert "compute_var_cvar" in ae.version()["tools"]


def test_var_cvar_golden_through_sdk():
    rng = np.random.default_rng(99)
    rets = (rng.normal(0.0005, 0.012, 500) - 0.0008 * (rng.random(500) > 0.95)).tolist()
    env = ae.compute_var_cvar(rets)
    assert env["determinism"] == "exact"
    assert env["engine_version"].startswith("quant_core@")
    assert env["result"]["parametric"]["var_pct"] == 2.02


def test_deflated_sharpe_golden_through_sdk():
    rets = np.random.default_rng(42).normal(0.0008, 0.018, 300).tolist()
    out = ae.deflated_sharpe(rets, n_trials=50)["result"]
    assert out["deflated_sharpe"] == 0.0134
    assert out["verdict"] == "likely_noise"


def test_typed_error_raises():
    with pytest.raises(AlphaEngineError) as e:
        ae.deflated_sharpe([0.01, 0.02, 0.03], n_trials=10)
    assert e.value.code == "INSUFFICIENT_OBSERVATIONS"
    assert e.value.request_id


def test_find_pairs_through_sdk():
    rng = np.random.default_rng(2024)
    trend = np.cumsum(rng.normal(0, 0.01, 300))
    a = np.exp(3.0 + trend + 0.01 * rng.normal(0, 1, 300)).tolist()
    b = np.exp(2.0 + 0.8 * trend + 0.01 * rng.normal(0, 1, 300)).tolist()
    out = ae.find_cointegrated_pairs({"AAA": a, "BBB": b}, cointegrated_only=False)
    assert out["result"]["n_evaluated"] == 1
