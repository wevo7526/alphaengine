# Test from your own Claude (production connection test)

> Proves the platform end to end: a real MCP client (your Claude) connects to
> the deployed gateway and calls a tool, getting back a real SignalEnvelope.
> This is the item-5 / item-6 acceptance test before the Tuesday release.

## 0. Deploy the gateway (one Railway service)

- New Railway service, **root = `mcp-server/`** (build context = `mcp-server/`).
- Build: the included `Dockerfile` (or Nixpacks + `Procfile`).
- Start: `uvicorn app:app --host 0.0.0.0 --port $PORT` (the `Procfile` does this).
- Env (see `.env.example`): set **`AUTH_STUB=0`**, **`MCP_API_KEYS=<yourkey>:owner`**,
  optionally `SANDBOX_API_KEY`. `PORT` is provided by Railway.
- After deploy you have a base URL, e.g. `https://alphaengine-gateway.up.railway.app`.
  REST is at `/v1/...`; MCP is at `/mcp`.

## 1. Smoke-test the REST door (no Claude needed)

```bash
BASE=https://<your-gateway-host>
curl $BASE/v1/health
curl $BASE/v1/status
curl -sS $BASE/v1/tools/compute_var_cvar \
  -H "Authorization: Bearer <yourkey>" \
  -H "Content-Type: application/json" \
  -d '{"portfolio_returns":[0.004,-0.011,0.006,0.013,-0.002,0.009,-0.014,0.007,0.003,0.011,-0.006,0.002,0.008,-0.009,0.005,0.001,0.010,-0.004,0.006,-0.003,0.007,0.012,-0.008,0.004,0.009,-0.005,0.003,0.006]}'
```
Expect a `SignalEnvelope` with `determinism: "exact"` and a populated `result`.
A bad key returns `AUTH_INVALID`; too few points returns `INSUFFICIENT_OBSERVATIONS`.

## 2. Connect your Claude (the MCP door)

**Claude Desktop** — add to the MCP servers config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "alphaengine": {
      "url": "https://<your-gateway-host>/mcp/",
      "headers": { "Authorization": "Bearer <yourkey>" }
    }
  }
}
```

Note the trailing slash on `/mcp/` (the streamable endpoint is mounted at that
path). Verified locally: `POST /mcp/` with an `initialize` returns
`serverInfo.name = "alphaengine"`. Restart Claude Desktop. The six tools (`compute_var_cvar`, `deflated_sharpe`,
`pbo_cscv`, `compute_spread_signal`, `find_cointegrated_pairs`,
`decompose_factors`) should appear.

**claude.ai custom connector** — add a custom MCP connector pointing at
`https://<your-gateway-host>/mcp/` with the bearer header.

## 3. Drive it from chat

Paste a prompt like:

> Using the alphaengine MCP server, run `compute_var_cvar` on these daily
> returns [ ... 30 numbers ... ] and tell me the 95% VaR, the CVaR, and the
> engine_version.

Then:

> Run `deflated_sharpe` on the same returns with n_trials 240 and tell me the
> verdict (edge / inconclusive / likely_noise).

**Pass criteria:** Claude discovers the tools, calls one, and returns the
envelope fields. The `engine_version` is stamped. A noise stream comes back
`likely_noise`. Nothing you sent is stored (telemetry on `/v1/status` shows
counts/latency only).

## 4. What this does NOT cover yet

The agent-slate plane (the async desk over MCP) is T7 and not in this build; the
connection test covers the deterministic plane, which is what proves the live
MCP handshake + the contract.
