"""
T7 tests — the agent-job plane. The desk is mocked (jobs._run_desk) so the job
lifecycle, provided-mode seam, and memo->envelope mapping are tested without an
LLM or API key. HTTP shape (submit / not-found / validation) tested via TestClient.
"""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import jobs
from api import app

client = TestClient(app)
_MEMO = json.loads((Path(__file__).parent / "fixtures" / "sample_memo.json").read_text())


async def _fake_desk(query, data):
    # The desk runs on the backend (proxied); the gateway maps memo -> envelope.
    return dict(_MEMO)


def test_job_lifecycle_direct(monkeypatch):
    monkeypatch.setattr(jobs, "_run_desk", _fake_desk)
    job_id = jobs.create_job(owner="local")
    asyncio.run(jobs.run_agent_job(job_id, "best L/S in industrials?", {"fundamentals": {}}, "req_t"))
    job = jobs.get_job(job_id)
    assert job["status"] == "done"
    env = job["envelope"]
    assert env["determinism"] == "agent"
    assert len(env["signals"]) == 3
    assert env["signals"][0]["instruments"][0]["symbol"] == "ASLE"


def test_failed_desk_marks_job_failed(monkeypatch):
    async def _boom(query, data):
        raise RuntimeError("desk exploded")
    monkeypatch.setattr(jobs, "_run_desk", _boom)
    job_id = jobs.create_job(owner="local")
    asyncio.run(jobs.run_agent_job(job_id, "q", None, "req_t"))
    job = jobs.get_job(job_id)
    assert job["status"] == "failed"
    assert "desk exploded" in job["error"]


def test_submit_returns_job_id():
    r = client.post("/v1/jobs", json={"query": "find a pair trade in regional banks"})
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"].startswith("job_")
    assert body["status"] == "queued"


def test_query_required():
    r = client.post("/v1/jobs", json={"query": "   "})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "SCHEMA_INVALID"


def test_unknown_job_is_404():
    r = client.get("/v1/jobs/job_nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_job_does_not_retain_payload():
    # The submitted data payload must never be stored on the job record.
    job_id = jobs.create_job(owner="local")
    job = jobs.get_job(job_id)
    assert "data" not in job and "payload" not in job
