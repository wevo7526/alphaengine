# AlphaEngine MCP Server — Finalized Build Plan

> **Status:** planned, not built. Pick up at "Build order → Step 1" tomorrow.
> **One-line:** a stateless, no-data computation service. The fund brings its
> own licensed market data in the tool call; we run the quant math and hand
> the result back. We never source, store, or redistribute data — so there is
> **no data license to buy** ($1k+/mo problem disappears) and **no client data
> to leak** (trust posture for funds).

---

## Why this is the product (not the data SaaS)

Commercial market-data redistribution requires exchange licensing ($1k+/mo
minimum; options via OPRA is more). The free tiers are non-commercial. So the
Massive-based app is a **demo/dev tool only** — it cannot be sold. The MCP
server is the **only legally monetizable path**: the data-licensing question
becomes the fund's (they already pay for it), and our engine is data-agnostic.

The engine is the asset; it's already separable. Verified: the core math in
`backend/quant/*` is array-level pure functions; only the top-level
orchestrators (`analyze_pair`, `build_proxy_factor_returns`) fetch data, and
the MCP tools bypass those by taking data as input.

---

## Locked decisions

| Decision | Choice |
|---|---|
| Location | **`mcp-server/` subdirectory** in this monorepo (Railway service, root dir = `mcp-server/`). |
| Scope | **The whole quant engine** as stateless tools — the 4 required + the expanded catalog below. |
| Architecture | Stateless, no fetching, no storage of inputs, nothing retained between calls. |
| Transport | **FastMCP, HTTP/streamable** (remote; funds connect over HTTPS). |
| Quant code | **Copied** into `mcp-server/quant_core/` (self-contained — NO import from `alpha-backend`, NO data layer). |
| Auth | Per-client API key on every request → client identity; `AUTH_STUB` env toggle for local. |
| Data input | **Inline JSON first.** Mark (don't build) the v2 "upload + reference by ID" extension for large universes. |

---

## Service layout (`mcp-server/`)

```
mcp-server/
  server.py            # FastMCP app, tool registration, HTTP transport, auth middleware
  auth.py              # per-client key check + AUTH_STUB bypass (config change to harden)
  schemas.py           # Pydantic typed input/output models per tool
  quant_core/          # PURE functions, copied/extracted from backend/quant (no data deps)
    pairs.py           #   cointegration, hedge ratio, half-life, spread/z-score
    factors.py         #   OLS factor regression + attribution
    risk.py            #   VaR/CVaR, Ledoit-Wolf shrinkage, correlation
    performance.py     #   Sharpe/Sortino/Calmar/drawdown/alpha/beta/rolling
    overfitting.py     #   deflated Sharpe, PBO/CSCV, purged CV, bootstrap CI
    optimizer.py       #   Black-Litterman, mean-variance
    portfolio.py       #   HRP
    regime.py          #   HMM regime classify + size multiplier (+ rule fallback)
    options.py         #   put/call, IV skew, implied move, max pain, Greeks
    signal_validation.py # IC, ICIR, hit-rate-by-conviction, alpha decay
    conviction.py      #   decomposable conviction composite + calibration/Brier
    stress.py          #   macro-shock scenario on supplied positions
    curve.py           #   yield-curve / key-rate analytics
  tests/               # unit tests: each pure fn on sample supplied data (Step 1)
  requirements.txt     # fastmcp, statsmodels, numpy, pandas, scipy, scikit-learn, hmmlearn, pydantic
  railway.toml         # service config (root dir, start command)
  .env.example
  README.md            # deploy + connect-from-Claude + per-tool data formats & example payloads
```

**Railway:** new service in the existing project, root dir `mcp-server/`, Python
auto-detected, start command launches FastMCP HTTP bound to `0.0.0.0:$PORT`.
Env: `MCP_API_KEYS` (key store), `AUTH_STUB` (on/off), `PORT` (injected). No
backend URL — fully self-contained.

---

## Tool catalog ("all of it and more")

Every tool: **data in → compute → structured out**, nothing retained. Each gets
a typed schema and an LLM-facing description (what it does, exact data format,
size limits, output). ★ = the four required tools.

### Pairs / mean-reversion
1. ★ **find_cointegrated_pairs** — `{prices:{ticker:{date:close}}}` + sig level, max half-life → pairs with `{test_stat, p_value, half_life, z_score, hedge_ratio}`. *(quant_core/pairs)*
2. ★ **compute_spread_signal** — `{prices:{a,b}}` + z-window → `{spread, z_score, signal, half_life, hedge_ratio}`.
3. **adf_test** — stationarity of one supplied series → `{adf_stat, p_value, stationary}`.

### Factor / attribution
4. ★ **decompose_factors** — `{asset_returns, factor_returns}` → `{betas, r_squared, alpha, residual_vol, t_stats}`. *(quant_core/factors)*
5. **rolling_factor_exposures** — rolling betas over a supplied window.
6. **alpha_vs_factor_variance** — alpha-share vs factor-share decomposition.

### Screening / ranking
7. ★ **screen_universe** — `{metrics:{ticker:{field:val}}}` + `{filters, rank_by}` → ranked candidates with driving values. *(inline-small only; large = v2)*
8. **rank_cross_sectional** — composite-score rank over supplied metric panel.

### Risk
9. **compute_var_cvar** — parametric / historical / Cornish-Fisher + bootstrap VaR & CVaR on supplied returns. *(quant_core/risk)*
10. **covariance_shrinkage** — Ledoit-Wolf shrunk covariance from supplied returns.
11. **correlation_matrix** — correlation + rolling stability.
12. **stress_scenario** — apply a macro shock to supplied positions → per-position + portfolio impact. *(quant_core/stress)*

### Performance / backtest rigor (the moat)
13. **performance_report** — Sharpe, Sortino, Calmar, max drawdown, alpha/beta, VaR/CVaR, rolling Sharpe on supplied returns. *(quant_core/performance)*
14. **deflated_sharpe** — DSR + PSR adjusting for trial count + skew/kurtosis. "We tell you when it's noise." *(quant_core/overfitting)*
15. **probability_of_backtest_overfitting** — PBO via CSCV on a supplied PnL matrix.
16. **purged_kfold_split** — purged + embargoed CV indices for supplied label timestamps (leakage-free splits).
17. **bootstrap_sharpe_ci** — bootstrap CI for the Sharpe.

### Portfolio construction
18. **optimize_black_litterman** — weights from supplied covariance + views (conviction→omega). *(quant_core/optimizer)*
19. **optimize_hrp** — HRP weights from supplied covariance (no matrix inversion). *(quant_core/portfolio)*
20. **mean_variance_optimize** — with transaction costs / constraints.

### Regime
21. **classify_regime** — from supplied macro series (VIX, credit, yield curve) → regime posterior + position-size multiplier; HMM with rule-based fallback for short inline windows. *(quant_core/regime)*

### Options (this is how options "comes back" — BYO chain)
22. **options_analytics** — put/call ratio, IV skew, implied move, ATM IV, max pain, Greeks from a **supplied** options chain. The fund passes their licensed chain; we never source it. *(quant_core/options)*

### Signal quality / conviction
23. **signal_ic** — IC, ICIR, hit-rate-by-conviction, alpha decay from supplied signals + forward returns. *(quant_core/signal_validation)*
24. **conviction_composite** — decomposable conviction from supplied sub-scores + reliability/Brier. *(quant_core/conviction)*
25. **yield_curve_analytics** — key-rate durations + curve shape from supplied yields. *(quant_core/curve)*

> ~25 tools = the full engine. Demo-first subset (sharpest, fit inline cleanly):
> `find_cointegrated_pairs`, `compute_spread_signal`, `deflated_sharpe`,
> `performance_report`, `compute_var_cvar`.

---

## Data contract & size limits

- **Inline JSON** in the call. Pairs / spread / risk / performance / factor are
  small and fit cleanly. Document per-tool the exact format + practical caps
  (e.g. ~handful of tickers, ~2y daily for cointegration).
- **v2 (not now):** "upload data, reference by ID" for fund-scale universes.
  Mark the ingest boundary with `# TODO(v2): data-by-reference` so it slots in
  without rework. **Do not promise universe-scale screening to a fund until v2.**

## Auth

- Per-client API key checked on every request, mapped to a client identity.
- `AUTH_STUB=true` → single dev key / bypass for local testing; real key-store
  structure so hardening is config, not a rewrite.
- README sells the **stateless isolation**: no stored client data exists, each
  request is processed and discarded — make it true, document it.

---

## Build order (start here tomorrow)

1. **Extract `quant_core/` + unit-test on sample supplied data — NO server yet.**
   Copy the pure functions out of `backend/quant/*`; for the tangled
   orchestrators, lift only the inner array-level math. Prove each tool's math
   is correct on data passed in. *This is the foundation — do it first and show
   it working before anything else.*
2. Define `schemas.py` (Pydantic input/output) per tool.
3. Wrap as FastMCP HTTP tools with LLM-facing descriptions + example payloads.
4. Stubbed auth (`AUTH_STUB`).
5. Deploy as a new Railway service (root `mcp-server/`).
6. Connect from a Claude client and test each tool end-to-end with sample data.

## Risks / flags

- **Inline size limit** is real — demo on pairs/spread/risk; large screening is v2.
- **Regime HMM** needs a fit on the supplied window; `hmmlearn` on short inline
  data is unstable → ship the rule-based fallback (already in `regime.py`).
- **Extraction tangle** is only at the top (`analyze_pair`,
  `build_proxy_factor_returns`) — extract the pure inner functions, leave the
  fetchers in `alpha-backend`.
- **FastMCP HTTP transport** — confirm the current FastMCP streamable-HTTP API
  against installed version before wiring tools.
- **Dependency footprint** (statsmodels/scipy/hmmlearn) is fine on Railway.

## Out of scope (explicitly)
Data fetching of any kind, any DB, any caching of client inputs, session state,
v2 data-by-reference, universe-scale screening, the demo SaaS's data layer.
