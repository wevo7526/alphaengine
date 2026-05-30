"""
Deterministic REST surface (T6) — the algo's door.

Synchronous POST data -> versioned result, no LLM, for the six quant_core tools.
The quant_core functions are pure (no data layer, no network, no LLM), so this
plane satisfies the determinism + no-fetch + LLM-barred invariants by
construction. Every response carries the versioned header (schema_version,
engine_version, request_id, generated_at, determinism="exact").

Shape note: the analytic tools (deflated_sharpe, pbo_cscv, compute_var_cvar,
decompose_factors) return their computation in `result`; these are the
validation/risk building blocks that populate a signal's blocks on the agent
plane. The signal-producing tools (compute_spread_signal, find_cointegrated_pairs)
likewise return their native result here. The full signals[] SignalEnvelope is
emitted by the agent plane (T7); see docs/SIGNAL_ENVELOPE.md. Auth + metering
layer on in T9/T10 — this module is the tool surface.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from contracts import ApiError, SchemaInvalid, TOOL_INPUTS, guard_body_size, parse_input
from envelope.models import SCHEMA_VERSION
from quant_core import (
    ENGINE_VERSION,
    compute_spread_signal,
    compute_var_cvar,
    decompose_factors,
    deflated_sharpe,
    find_cointegrated_pairs,
    pbo_cscv,
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or f"req_{uuid4().hex[:12]}"


class DeterministicEnvelope(BaseModel):
    schema_version: str = SCHEMA_VERSION
    engine_version: str = ENGINE_VERSION
    request_id: str
    generated_at: str
    determinism: str = "exact"
    tool: str
    result: dict
    warnings: list[str] = Field(default_factory=list)


# tool name -> (input model is in TOOL_INPUTS) ; here: how to call quant_core
def _run(tool: str, m) -> dict:
    if tool == "deflated_sharpe":
        return deflated_sharpe(m.returns, n_trials=m.n_trials, trials_sharpe_std=m.trials_sharpe_std)
    if tool == "pbo_cscv":
        return pbo_cscv(m.pnl_matrix, n_splits=m.n_splits, max_combos=m.max_combos)
    if tool == "compute_spread_signal":
        return compute_spread_signal(
            m.a_closes, m.b_closes, symbol_a=m.symbol_a, symbol_b=m.symbol_b,
            zscore_window=m.zscore_window, stability_window=m.stability_window,
        )
    if tool == "find_cointegrated_pairs":
        return find_cointegrated_pairs(
            m.prices, candidates=m.candidates, zscore_window=m.zscore_window,
            stability_window=m.stability_window, cointegrated_only=m.cointegrated_only,
        )
    if tool == "compute_var_cvar":
        return compute_var_cvar(
            m.portfolio_returns, confidence=m.confidence, horizon_days=m.horizon_days,
            portfolio_value=m.portfolio_value, bootstrap_samples=m.bootstrap_samples,
        )
    if tool == "decompose_factors":
        return decompose_factors(m.portfolio_returns, m.factor_returns, risk_free_rate=m.risk_free_rate)
    raise SchemaInvalid(f"no runner for tool {tool!r}")


app = FastAPI(title="AlphaEngine — deterministic API", version=SCHEMA_VERSION)


@app.get("/v1/health")
async def health():
    return {"status": "ok", "schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION}


@app.get("/v1/version")
async def version():
    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "tools": sorted(TOOL_INPUTS.keys()),
    }


@app.post("/v1/tools/{tool}")
async def run_tool(tool: str, request: Request):
    request_id = _request_id(request)
    try:
        if tool not in TOOL_INPUTS:
            raise SchemaInvalid(f"unknown tool {tool!r}", details={"tools": sorted(TOOL_INPUTS)})
        raw = await request.body()
        guard_body_size(len(raw))
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise SchemaInvalid("request body is not valid JSON")
        model = parse_input(TOOL_INPUTS[tool], body)
        result = _run(tool, model)
        env = DeterministicEnvelope(request_id=request_id, generated_at=_now(), tool=tool, result=result)
        return JSONResponse(env.model_dump())
    except ApiError as e:
        return JSONResponse(e.to_dict(request_id), status_code=e.http_status)
