# T2 — Interaction patterns: sync deterministic, async agent job

> Resolves the architectural gap the build spec flags: the two planes have
> different latency profiles and therefore different request shapes. This note
> names the mechanism so T6 (REST) and T7 (agent job) build against it.

## The rule

**Math = synchronous. Desk = asynchronous job.** Both are reachable from both
doors (REST and MCP). It is *not* "REST = sync, MCP = async."

```
 DETERMINISTIC PLANE  (quant_core)        PROBABILISTIC PLANE  (agent desk)
 ──────────────────────────────          ─────────────────────────────────
 pure math, sub-second                    5-agent LangGraph, tens of sec–min
 POST data → envelope (one response)      submit → job_id → poll/stream → envelope
 idempotent (same input→same output)      NOT idempotent (LLM); optional input-hash cache
 REST: POST /v1/signals/*                 REST: POST /v1/jobs → GET /v1/jobs/{id}[/stream]
 MCP: tool returns immediately            MCP: tool starts job, returns job_id; a second
                                               tool/stream retrieves the terminal envelope
```

Why: the desk runs up to interpreter 45s + research 180s + risk 90s + strategy
90s + CIO 120s (see INVENTORY §3). Wrapping that in a synchronous request times
out at every proxy in the path. So the desk is a job.

## The job mechanism (named)

- **Transport for progress:** reuse the backend's existing **SSE** stream
  (`agents/stream_callbacks.py` + the `text/event-stream` endpoint in
  `backend/main.py`). The gateway does not invent a new streaming protocol.
- **Job registry:** an in-process `dict[job_id, JobState]` in the gateway.
  `JobState = {status: queued|running|done|failed, created_at, envelope?, error?,
  input_hash}`. A background task runs `orchestrator.run_research_desk(...)` and,
  on completion, maps the memo → `SignalEnvelope` and stores it on the job.
- **Lifecycle:**
  1. `POST /v1/jobs` (or MCP `start_signal_slate`) → validate input → create
     `job_id` → kick off the desk in the background → return `{job_id, status:"queued"}`.
  2. `GET /v1/jobs/{job_id}` → current status (+ terminal `envelope` when done).
  3. `GET /v1/jobs/{job_id}/stream` → SSE passthrough of the run, terminating
     with the final envelope event.
- **TTL / statelessness:** job entries expire on a short TTL (default 15 min)
  and are evicted after the terminal envelope is retrieved. **No client payload
  is persisted** — the supplied data lives only for the duration of the run, in
  memory, then is discarded with the job. This keeps invariant #1 (nothing
  stored) intact; the registry holds status + the computed envelope, never the
  input data, beyond the run.
- **Idempotency:** the deterministic plane is idempotent — safe to retry.
  The agent plane is **not** (LLM nondeterminism); we document this and offer an
  optional `input_hash` short-TTL cache so an accidental duplicate submit can
  return the in-flight/just-finished job rather than spawning a second desk run.
  Idempotency keys are opt-in, never assumed.

## Scope note

T6 builds the synchronous deterministic endpoints first (they only need
quant_core + the envelope, both done/next). T7 builds the job surface over the
backend orchestrator once the seam (T5) lets the desk run on provided data.
A single-process in-memory registry is the beta mechanism; a durable queue
(Redis/RQ) is a v2 concern, not now.
