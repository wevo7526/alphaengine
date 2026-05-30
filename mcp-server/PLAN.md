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

---

# SHIP DIRECTION — repositioning the whole product

The licensing reality ($1k+/mo for any commercial market data; options worse;
free tiers non-commercial) forces a clean two-surface split. This section is
the map for moving the ship.

## The two surfaces

| | **AlphaEngine app (the demo)** | **MCP server (the product)** |
|---|---|---|
| Purpose | Show prospects the engine + agents + UI | The thing we sell seats to |
| Data | **yfinance** (free, generous, **non-commercial → personal/eval/demo ONLY**) | **None.** The fund brings their licensed data in the call |
| Commercial? | No — never sold, never paid-customer-driven | Yes — legally clean (we never touch data) |
| Who runs it | Us, to demo. Optionally a customer's BYO-data instance (perk) | The fund, over HTTPS |
| Status | revert to yfinance + button up | build (this plan) |

**The rule that keeps it legal:** a *paying customer* must never be driven by
data **we** source. They either watch our demo (we drive it, eval use) or run
the frontend perk on **their own** data through the MCP. Money near data we
supply = commercial use of that data. Keep our hands off the data.

## How we sell it

> **Buy AlphaEngine MCP seats** — your licensed data, our agents + quant engine.
> Stateless: nothing sourced, nothing stored, nothing to leak.
> **The AlphaEngine desk UI is included** — a research frontend that runs on
> *your* data through the MCP. Memos, slates, cointegration, risk, deflated
> Sharpe — on data you already pay for.

The frontend is a **perk/differentiator**, not a separately-sold data app, and
in a customer's hands it is **BYO-data** (talks to the MCP + a customer data
adapter; the yfinance path is demo-only and disabled for customers).

---

## Workstream 1 — Revert AlphaEngine app to yfinance (button up the demo)

Goal: the demo works freely again (no Massive 5/min wall), same data shapes.
The Massive migration already preserved the contract, so this is a source swap.

**Surgical revert (preserves post-migration product logic — idea-count 5/10
split, discovery blend, provenance, NLP — which live in the agents, not the
data layer):**

1. Restore the **pure data files** to their pre-migration (yfinance) state from
   git (commit just before `0ea54a9` "Migrate market data + news to Massive"):
   - `backend/data/market_client.py` (yfinance prices/fundamentals/options)
   - `backend/data/news_client.py` (NewsAPI + Finnhub)
   - `backend/data/market_screener.py` (`yf.screen` + AV movers)
   - `backend/data/alpha_vantage_client.py` (restore deleted — RSI/MACD/movers)
   - `backend/tests/test_screener.py` (asserts `yfinance_screener`)
2. `requirements.txt`: re-add `yfinance`, `finnhub`/`finnhub-python`,
   `newsapi-python`. (Massive needs no SDK; leaving `massive_client` unused is
   harmless, or delete it + its tests.)
3. `config.py`: re-add `FINNHUB_API_KEY`, `NEWS_API_KEY` (+ keep `ALPHA_VANTAGE_KEY`).
   Keep `MASSIVE_API_KEY` field (unused) or remove. `data_sources` display →
   Yahoo Finance / FRED / sec-api / Firecrawl / Finnhub / NewsAPI.
4. Revert the **three consumers** that were rewired to Massive/price-tape back to
   `MarketDataClient` (yfinance has no hard rate cap, so per-ticker is fine for
   a demo):
   - `agents/orchestrator.py::_fetch_live_prices_for` → `get_fundamentals` per ticker
   - `main.py /api/portfolio/positions` → `get_fundamentals` per ticker
   - `infra/eod_snapshot.py::_batch_close_prices` → `get_fundamentals`
5. Decide on the **price tape**: it was a Massive optimization. For yfinance it
   is unnecessary — either remove (`data/price_tape.py`, the model/repo/endpoint,
   `tests/test_price_tape.py`) or leave dormant (consumers no longer call it).
   Cleanest: remove it with the Massive layer.
6. Re-add to Railway: `FINNHUB_API_KEY`, `NEWS_API_KEY`. (Demo keys; non-commercial use.)
7. Verify: full pytest green, `main` boots, a memo run prices + marks the
   portfolio, screener returns names.

**Keep (do NOT revert):** all agent/quant/provenance/NLP/marketing work — none
of it is data-layer. The 5-primary/10-secondary split + discovery blend stay.

---

## Workstream 2 — Marketing reposition (MCP-first)

The site currently sells "AI Agents for Investment Managers" (a data app). Re-aim
it at the MCP, with the app as a demo/perk. Keep the institutional design system.

- **Hero** → the engine, not the data app. e.g. *"The quant research engine your
  desk runs on its own data."* Subhead: stateless MCP, BYO-data, agents + math,
  nothing stored.
- **New section: "How it works"** — the no-data flow: your data → MCP tools →
  results → your desk UI. Sell the **trust posture** (we never touch your data).
- **Reframe the existing product/intelligence sections** as *what the engine
  computes* (cointegration, factor decomposition, deflated Sharpe, risk), not
  *what data we pull*.
- **The frontend** becomes "included desk UI (runs on your data)," not the
  headline product.
- **"Try the demo"** CTA → the yfinance app, clearly labeled a demo on sample
  data (sets the eval-use framing explicitly).
- Drop any copy implying we supply market data commercially.

## Workstream 3 — Clerk × MCP auth (seats)

Two layers, cleanly separated:
- **Clerk = human identity + billing/seats** (sign-in/up, orgs, plan). Already in
  the app; reuse for the customer dashboard.
- **MCP = machine auth via per-client API key** (checked on every HTTPS request;
  `AUTH_STUB` for local).

**Bridge:** on Clerk sign-up / seat purchase, **provision an MCP API key** mapped
to that Clerk org/user (store the key→identity map; the MCP server validates the
key, the app manages issuance/rotation). Sign-up flow:
1. Clerk sign-up → org/seat created.
2. App provisions an MCP key for the org (Clerk org id → key).
3. Dashboard shows the key + the **connection snippet** (MCP server URL + key)
   to paste into the fund's Claude/agent client.
4. Revocation/rotation = app action that updates the key store the MCP reads.

Sign-in/up pages get repositioned: "Connect your desk to the AlphaEngine MCP" —
not "log into the data app." Keep the institutional reskin.

## Workstream 4 — Frontend BYO-data mode (the perk, productized)

The included frontend, in a customer's hands, must be no-(our)-data:
- A **data adapter** the customer configures (their feed / file upload / their
  own MCP-data source) feeds the same shapes the engine expects.
- The frontend calls the **MCP server** for all computation (cointegration,
  risk, etc.) instead of the backend's quant endpoints.
- The **yfinance path is demo-only**, hard-disabled for authenticated customers.
- `# TODO`: this is the larger build; v1 can ship MCP + demo, with the BYO-data
  frontend as fast-follow.

---

## Sequencing (move the ship)

1. **Revert app → yfinance** (Workstream 1) — button up the demo. *First.*
2. **Build the MCP** (Build order above) — quant_core + tools + deploy. *The product.*
3. **Reposition marketing** (Workstream 2) — MCP-first, app as demo/perk.
4. **Clerk × MCP keys** (Workstream 3) — seat provisioning + connection UX.
5. **BYO-data frontend mode** (Workstream 4) — the perk, productized. *Fast-follow.*

Legal: have a lawyer bless the no-data structure + the demo/eval framing before
selling. The principle is sound (we're outside the data license's scope, not
working around it), but it's a litigated area — cheap consult, worth it.
