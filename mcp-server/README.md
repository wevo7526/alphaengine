# AlphaEngine — gateway (mcp-server)

The signal-infrastructure layer: a thin gateway over the intact backend that
turns supplied data into a validated, cited, risk-gated **SignalEnvelope**, with
**two front doors over one core** and **nothing stored**.

```
  execution bot (HTTP/JSON)        AI agent (MCP / JSON-RPC)
        │                                  │
        ▼                                  ▼
     api.py  ───────────┐      ┌───────── server.py     ← two thin adapters
                        ▼      ▼
              ONE CORE (in-process Python)
              • quant_core/*        deterministic math (pure, pinned)
              • agent desk          probabilistic reasoning (reuses backend orchestrator)
              • SignalEnvelope      the single output contract
                        │
                        ▼
              the SAME SignalEnvelope · nothing retained
```

**REST and MCP do not call each other.** They are sibling adapters that invoke
the same in-process functions. Both expose the deterministic tools (synchronous)
and the agent desk (an async job). See `docs/MASTER_PLAN.md`,
`docs/SIGNAL_ENVELOPE.md`, and `docs/INVENTORY.md`.

## Layout

```
mcp-server/
  quant_core/        # deterministic plane — pure functions, no data layer, no LLM
    validation.py    #   deflated_sharpe, pbo_cscv            [T1 ✓]
    pairs.py         #   find_cointegrated_pairs, spread      [T1 pending]
    risk.py          #   compute_var_cvar                     [T1 pending]
    factors.py       #   decompose_factors                    [T1 pending]
  tests/             # golden-output fixtures (CI fails on drift)
  docs/              # plan, marketing, envelope contract, inventory
  requirements.txt   # numeric stack pinned EXACTLY (determinism contract)
  pytest.ini
  # api.py, server.py, envelope/, seam/  — land in T3–T8
```

## Develop / test

Uses the backend venv (shares the pinned numeric stack during the build):

```
../backend/.venv/Scripts/python.exe -m pytest        # from mcp-server/
```

## Invariants (never violate — see MASTER_PLAN §4)

1. No data sourced or stored. Stateless. Telemetry logs shapes/latency, never values.
2. Authenticated/paying requests run only in data-provided mode; fetch is unreachable.
3. The LLM never computes a number the algo consumes (deterministic plane is LLM-free).
4. Determinism on the algo plane: pinned deps, golden tests, `engine_version` stamped.
5. The validator gates rigor AND provenance: no `verdict: "edge"` without `validation`.
