"""
T13 tests — telemetry + /v1/status, and the combined deploy app imports.
"""

from fastapi.testclient import TestClient

import telemetry
from api import app

client = TestClient(app)


def test_status_reports_versions_and_metrics():
    telemetry.reset()
    client.get("/v1/health")
    client.get("/v1/health")
    body = client.get("/v1/status").json()
    assert body["engine_version"].startswith("quant_core@")
    assert body["schema_version"] == "1.0.0"
    assert body["requests"] >= 2
    assert "latency_ms" in body and "by_route" in body


def test_telemetry_records_no_values():
    # The snapshot only ever exposes route keys + counts/latency, never values.
    telemetry.reset()
    client.post("/v1/tools/compute_var_cvar", json={"portfolio_returns": [0.01, -0.02, 0.01, 0.0] * 8})
    snap = telemetry.snapshot()
    assert "/v1/tools/compute_var_cvar" in snap["by_route"]
    blob = repr(snap)
    assert "0.01" not in blob and "portfolio_returns" not in blob


def test_combined_app_imports():
    import app as deploy_app
    assert deploy_app.app is not None
