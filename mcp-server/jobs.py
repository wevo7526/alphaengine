"""
Agent-job plane (T7) — the probabilistic surface as an async job.

The 5-agent desk takes tens of seconds to minutes, so it can't be a synchronous
request. A job: submit -> job_id -> poll/stream -> terminal SignalEnvelope
(determinism="agent", thesis populated). Both REST (api.py) and MCP (server.py)
drive this registry.

Statelessness: the registry holds job STATUS + the computed envelope only. The
caller's input `data` payload lives in memory for the run and is then discarded
with the local frame — never stored on the job. Entries expire on a TTL.

No-fetch: the desk runs inside the data-provided seam, so market-data fetches
raise FetchForbidden unless supplied in `data`. The network guard is OFF here on
purpose — the agent reasoning needs LLM egress; the per-client method wrappers
(not a DNS block) are what enforce "no market data fetched".
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Optional

from envelope.builder import build_envelope_from_memo
from quant_core import ENGINE_VERSION

_TTL_SECONDS = 900  # 15 min
_lock = threading.Lock()
_JOBS: dict[str, dict] = {}


def _now() -> float:
    return time.time()


def _evict_expired() -> None:
    cutoff = _now() - _TTL_SECONDS
    with _lock:
        for jid in [j for j, v in _JOBS.items() if v["created_at"] < cutoff]:
            _JOBS.pop(jid, None)


def create_job(owner: str) -> str:
    _evict_expired()
    jid = "job_" + uuid.uuid4().hex[:16]
    with _lock:
        _JOBS[jid] = {
            "job_id": jid,
            "owner": owner,
            "status": "queued",   # queued | running | done | failed
            "phase": None,
            "created_at": _now(),
            "envelope": None,
            "error": None,
        }
    return jid


def get_job(job_id: str) -> Optional[dict]:
    with _lock:
        v = _JOBS.get(job_id)
        return dict(v) if v else None


def _set(job_id: str, **fields) -> None:
    with _lock:
        if job_id in _JOBS:
            _JOBS[job_id].update(fields)


async def _run_desk(query: str, data: Optional[dict]) -> dict:
    """Run the agent slate and return the memo as a dict.

    Proxies to the backend desk (which has the LLM + data clients + the model
    tiering), keeping the gateway image lean. Configured via GATEWAY_BACKEND_URL
    + INTERNAL_API_SECRET. Tests monkeypatch this to return a canned memo.
    """
    import os

    import httpx

    base = os.getenv("GATEWAY_BACKEND_URL")
    secret = os.getenv("INTERNAL_API_SECRET")
    if not base or not secret:
        raise RuntimeError(
            "agent slate unavailable: set GATEWAY_BACKEND_URL + INTERNAL_API_SECRET on the gateway"
        )
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(
            f"{base.rstrip('/')}/api/internal/slate",
            json={"query": query, "data": data},
            headers={"X-Internal-Secret": secret},
        )
        r.raise_for_status()
        return r.json()


async def run_agent_job(job_id: str, query: str, data: Optional[dict], request_id: str) -> None:
    """Background task: run the slate, store the terminal SignalEnvelope."""
    _set(job_id, status="running", phase="researching")
    try:
        memo = await _run_desk(query, data)
        envelope = build_envelope_from_memo(
            memo, request_id=request_id, engine_version=ENGINE_VERSION, determinism="agent",
        )
        _set(job_id, status="done", phase="done", envelope=envelope.model_dump())
    except Exception as e:  # noqa: BLE001 — surface as a failed job, never crash the loop
        _set(job_id, status="failed", phase="error", error=str(e))


def public_view(job: dict) -> dict:
    """The client-facing job shape — no owner, no internals."""
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "phase": job.get("phase"),
        "envelope": job.get("envelope"),
        "error": job.get("error"),
    }
