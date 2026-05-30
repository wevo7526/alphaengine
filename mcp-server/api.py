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

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from contracts import ApiError, SchemaInvalid, TOOL_INPUTS, guard_body_size, parse_input
from contracts.errors import JobNotFound
from contracts.inbound import guard_float_count
from envelope.models import SCHEMA_VERSION
from gateway import Identity, require_call, usage_for
from jobs import create_job, get_job, public_view, run_agent_job
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

# CORS for the browser dev-sandbox. Lock to explicit origins via CORS_ORIGINS in
# production; bearer-token API, so credentials only with explicit origins.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=bool(_cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiError)
async def _api_error_handler(request: Request, exc: ApiError):
    # Catches typed errors raised in dependencies (auth/metering) and bodies.
    return JSONResponse(exc.to_dict(_request_id(request)), status_code=exc.http_status)


@app.middleware("http")
async def _telemetry_mw(request: Request, call_next):
    # No-data-safe: records route + status + latency only, never payloads.
    from telemetry import record
    t0 = time.perf_counter()
    response = await call_next(request)
    record(request.url.path, response.status_code, (time.perf_counter() - t0) * 1000.0)
    return response


@app.get("/v1/status")
async def status():
    from telemetry import snapshot
    return {"schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION, **snapshot()}


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


@app.get("/v1/usage")
async def usage(request: Request, identity: Identity = Depends(require_call)):
    # Stateless usage snapshot for this caller — counts only, never payloads.
    return usage_for(identity.client_id)


@app.post("/v1/tools/{tool}")
async def run_tool(tool: str, request: Request, identity: Identity = Depends(require_call)):
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


# ── Agent-job plane (T7) — async desk -> terminal SignalEnvelope ────────────

class JobSubmit(BaseModel):
    query: str
    data: Optional[dict] = None  # provided-mode payload; never stored on the job


@app.post("/v1/jobs")
async def submit_job(payload: JobSubmit, request: Request, identity: Identity = Depends(require_call)):
    """Submit an agent slate. Returns a job_id immediately; the desk runs in the
    background, provided-mode (never fetches market data), and the terminal
    SignalEnvelope lands on the job."""
    request_id = _request_id(request)
    query = (payload.query or "").strip()
    if not query:
        raise SchemaInvalid("query is required")
    if payload.data is not None:
        guard_float_count(payload.data)  # bound the inline provided payload
    job_id = create_job(owner=identity.client_id)
    asyncio.create_task(run_agent_job(job_id, query, payload.data, request_id))
    return {"job_id": job_id, "status": "queued"}


def _owned_job_or_404(job_id: str, identity: Identity) -> dict:
    job = get_job(job_id)
    if not job or job.get("owner") != identity.client_id:
        raise JobNotFound(f"no job {job_id!r} for this client")
    return job


@app.get("/v1/jobs/{job_id}")
async def job_status(job_id: str, request: Request, identity: Identity = Depends(require_call)):
    return public_view(_owned_job_or_404(job_id, identity))


@app.get("/v1/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request, identity: Identity = Depends(require_call)):
    _owned_job_or_404(job_id, identity)  # authorize before streaming

    async def gen():
        last_status = None
        for _ in range(900):  # ~15 min ceiling at 1s cadence
            job = get_job(job_id)
            if not job:
                break
            if job["status"] != last_status:
                yield f"data: {json.dumps(public_view(job), default=str)}\n\n"
                last_status = job["status"]
            if job["status"] in ("done", "failed"):
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(gen(), media_type="text/event-stream")
