# Security review — platform pass (pre-launch)

> Scope: the gateway (mcp-server: REST + MCP + seam + auth/metering + jobs), the
> backend desk + anonymous Demo Desk path, and the data-protection invariants.
> Findings below are FIXED in code with tests unless marked residual.

## Invariants verified

- **No data stored.** Telemetry records route + status + latency only; a test
  asserts no payload values appear in the snapshot (`test_status.py`). The agent
  job registry stores status + the computed envelope only; the input `data`
  payload is never written to the job (`test_jobs.py::test_job_does_not_retain_payload`).
- **No fetch on the paid path.** The data-provided seam wraps every backend
  data-client egress method; in provided-mode a missing datum raises
  `FetchForbidden` instead of fetching (`test_seam.py`). The agent job runs
  inside `provided_session` (`jobs.run_agent_job`).
- **LLM barred from the deterministic plane.** quant_core is pure math, no LLM,
  no network; golden tests pin determinism.
- **Per-user isolation.** Backend reads/writes filter by `user_id`; gateway jobs
  are per-owner (`_owned_job_or_404`). Demo identities are isolated per id.

## Findings + fixes

| # | Severity | Finding | Fix |
|---|---|---|---|
| F1 | High | `AUTH_STUB` defaulted **on** -> if the env var were unset in production, the gateway would bypass auth entirely. | Secure-by-default: default is now **off**; auth is enforced unless `AUTH_STUB=1` is explicitly set (local/dev). Test: `test_security.py::test_auth_secure_by_default_when_unset`. |
| F2 | Med-High | Demo 2/day model-run cap was keyed only on the client-generated `X-Demo-Id`, so rotating the id granted unlimited free Opus runs. | Cap now keyed on the demo id **and** the client IP (X-Forwarded-For aware); exceeding either denies. Tests: `test_security.py` (id-rotation blocked by IP; per-id still enforced). |
| F3 | Med | Backend CORS was `allow_origins=["*"]` with `allow_credentials=True` (invalid combo, over-permissive). Gateway had no CORS for the browser sandbox. | Both are env-driven via `CORS_ORIGINS`; credentials are enabled **only** with explicit origins, never with wildcard. Bearer-token API needs no cookie credentials. |

## T7 agent-job surface audit

- **Auth + metering:** `POST /v1/jobs`, `GET /v1/jobs/{id}`, `/stream` all go
  through `require_call` (key/identity + quota).
- **Isolation:** a client can only read its own jobs (owner check -> JOB_NOT_FOUND).
- **No retention:** the input payload is bounded (`guard_float_count`) and never
  stored on the job; only status + the derived envelope persist, on a 15-min TTL.
- **No-fetch:** network guard is intentionally **off** in the job (the agent
  needs LLM egress); the per-client method wrappers still block market-data
  fetches not present in `data`.
- Note: agent runs are metered as one gateway call. Consider a dedicated, lower
  agent-run quota tier before opening the agent plane broadly (cost control).

## Residual risks / deploy must-dos

1. **Set the gateway env in production:** `AUTH_STUB=0`, `MCP_API_KEYS=...`,
   `CORS_ORIGINS=<frontend origin(s)>`, rotate `SANDBOX_API_KEY` off the default,
   and `ANTHROPIC_API_KEY` (agent plane only). The backend already fails closed
   in prod without `CLERK_ISSUER`.
2. **Demo run counter is in-memory** (resets on redeploy). A redeploy only ever
   grants a few extra demo runs, never fewer; move to a durable counter
   (DB/Redis) if abuse appears.
3. **Agent provided-data contract.** The agent plane in provided-mode needs the
   caller to supply the data the desk would otherwise fetch; missing data
   degrades gracefully (FetchForbidden caught, agent works with less) rather
   than leaking a fetch.
4. **Secrets** are env-only; none are committed (`.env.example` has placeholders;
   the Clerk publishable key in the frontend is public by design).

## Test coverage

`tests/test_security.py`, `test_seam.py`, `test_gateway.py`, `test_jobs.py`,
`test_status.py`, `test_contracts.py`, plus the golden determinism suites. Full
gateway suite: 85 green.
