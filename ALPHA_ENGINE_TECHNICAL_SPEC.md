# ALPHA ENGINE — Technical Specification

## Project: AI-Powered Quantitative Trading Intelligence Platform

**Codename:** Alpha Engine
**Author:** William Evans — Dominion Group
**Version:** 2.0 — Hedge Fund Desk Architecture
**Date:** April 2026
**Repository Target:** `alpha-engine/` (monorepo)
**Deployment:** Railway (backend + frontend)
**Portfolio Integration:** https://portfolio-production-e865.up.railway.app/

---

## 1. VISION

Alpha Engine simulates how a long/short equity hedge fund operates — from idea screening through research, risk gating, portfolio construction, trade execution, and performance feedback. It is not a black-box trading bot. It is an AI-powered fund infrastructure where specialized agent "desks" perform the work that teams of analysts, PMs, and risk managers do at firms like Millennium, Citadel, and Point72.

The human operator (the "Managing Director") receives institutional-grade intelligence, makes the final call, and tracks P&L. The system learns from its own track record — scoring signals, retiring weak models, and promoting strong ones.

**The alpha is in the closed loop.** Generate signals → take positions → measure outcomes → adjust weights → repeat.

---

## 2. ARCHITECTURE — THE DESK MODEL

Modeled after multi-strategy pod shops. Each desk has 2 agents with distinct roles. Desks are sequential — each desk's output feeds the next. The pipeline runs on every analysis request and nightly on the screened universe.

```
┌─────────────────────────────────────────────────────────────────┐
│                     ALPHA ENGINE v2                              │
│                                                                 │
│  DESK 1: SCREENING           (runs nightly + on-demand)         │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │  Universe Scanner │  │  Signal Ranker    │                    │
│  │  Scans 200+ names │  │  Ranks by edge    │                    │
│  │  for anomalies    │  │  strength, filters │                   │
│  └────────┬─────────┘  └────────┬─────────┘                     │
│           └──────────┬──────────┘                                │
│                      ▼                                           │
│  DESK 2: RESEARCH            (per-ticker deep dive)             │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │  Data Analyst     │  │  Thesis Builder   │                    │
│  │  Gathers macro,   │  │  Synthesizes data │                    │
│  │  fundamentals,    │  │  into investment  │                    │
│  │  filings, news    │  │  thesis with edge │                    │
│  └────────┬─────────┘  └────────┬─────────┘                     │
│           └──────────┬──────────┘                                │
│                      ▼                                           │
│  DESK 3: RISK                (independent — CRO authority)      │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │  Macro Regime     │  │  Position Risk    │                    │
│  │  Analyst          │  │  Manager          │                    │
│  │  Classifies cycle │  │  VaR, factor exp, │                    │
│  │  regime, tail     │  │  correlation,     │                    │
│  │  risks, regime-   │  │  sector limits —  │                    │
│  │  conditional rets │  │  ENFORCED gates   │                    │
│  └────────┬─────────┘  └────────┬─────────┘                     │
│           └──────────┬──────────┘                                │
│                      ▼                                           │
│  DESK 4: PORTFOLIO CONSTRUCTION  (sizing + hedging)             │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │  Trade Structurer │  │  Hedge Architect  │                    │
│  │  Entry/stop/tgt,  │  │  Factor-neutral   │                    │
│  │  conviction-wtd   │  │  hedge baskets,   │                    │
│  │  sizing via B-L   │  │  tail protection  │                    │
│  └────────┬─────────┘  └────────┬─────────┘                     │
│           └──────────┬──────────┘                                │
│                      ▼                                           │
│  DESK 5: CIO / SYNTHESIS     (final sign-off)                   │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │  Memo Writer      │  │  Decision Gate    │                    │
│  │  Writes the       │  │  Go/no-go based   │                    │
│  │  intelligence     │  │  on conviction,   │                    │
│  │  memo for the MD  │  │  risk budget,     │                    │
│  │                   │  │  regime alignment  │                    │
│  └────────┬─────────┘  └────────┬─────────┘                     │
│           └──────────┬──────────┘                                │
│                      ▼                                           │
│  DESK 6: SCORECARD / P&L     (continuous feedback loop)         │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │  Signal Scorer    │  │  Attribution      │                    │
│  │  Tracks every     │  │  Analyst          │                    │
│  │  signal at 1d/5d/ │  │  Decomposes P&L   │                    │
│  │  20d, computes IC │  │  into factor vs   │                    │
│  │  per desk, hit    │  │  alpha, adjusts   │                    │
│  │  rate, decay      │  │  desk weights     │                    │
│  └──────────────────┘  └──────────────────┘                     │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    DATA LAYER                            │    │
│  │  FRED | Yahoo Finance | NewsAPI | Finnhub | SEC-API     │    │
│  │  Alpha Vantage | Firecrawl (web)                        │    │
│  ├─────────────────────────────────────────────────────────┤    │
│  │                    QUANT LAYER (pure math)               │    │
│  │  EWMA Cov | VaR/CVaR | HMM Regime | B-L Optimizer      │    │
│  │  BSM Greeks | Factor Decomposition | Signal Validation   │    │
│  │  Performance Metrics | Backtesting                       │    │
│  ├─────────────────────────────────────────────────────────┤    │
│  │                    STORAGE                               │    │
│  │  PostgreSQL (Railway) | In-memory caches (TTL)           │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. DESK SPECIFICATIONS

### Desk 1: Screening Desk

**Purpose:** Find tradeable opportunities without human input. Runs nightly and surfaces the morning's watchlist.

**Agent 1A — Universe Scanner**
- Scans a universe of 200+ tickers (S&P 500 sectors, key ETFs, user watchlist)
- Detects: unusual volume, price breakouts/breakdowns, insider clusters, earnings surprises, RSI extremes, sentiment shifts, 8-K filings
- Uses: `market_client`, `news_client`, `sec_client`, `fred_client`
- Output: List of flagged tickers with anomaly type and priority score

**Agent 1B — Signal Ranker**
- Takes Scanner output and ranks by edge strength
- Cross-references anomalies against macro regime (regime-aware filtering)
- Filters out crowded trades (too many funds in the same name)
- Output: Top 10-20 ranked opportunities with signal type and estimated edge

**What exists today:** Morning report endpoint generates a daily briefing, but it's a single LLM call without systematic screening. `market_client`, `news_client`, `sec_client` all exist and can be used by the Scanner.

**What needs to be built:**
- Universe definition (configurable ticker list per user)
- Scanner agent with anomaly detection tools (wrapping existing quant modules)
- Ranker agent with regime-conditional filtering
- `WatchlistRecord` model + CRUD endpoints
- Nightly cron trigger (manual trigger first, automated later)

---

### Desk 2: Research Desk

**Purpose:** Deep dive on flagged tickers. Gather all relevant data and build a quantitative investment thesis.

**Agent 2A — Data Analyst**
- Executes the data gathering plan: macro snapshot, fundamentals, price history, options chain, news, SEC filings, sentiment scoring
- Uses all 5 data clients + NLP sentiment + options analytics
- Output: Structured `ResearchData` with quantitative facts

**Agent 2B — Thesis Builder**
- Synthesizes raw data into a coherent investment thesis
- Identifies the edge: what does the market miss? Why is this mispriced?
- Compares current valuation to historical range and sector peers
- Output: Investment thesis with bull/bear/base case scenarios and catalysts

**What exists today:** `ResearchAnalyst` agent does both data gathering AND thesis building in one agent. Splitting into 2 agents gives better focus and reduces the tool-calling iteration problem.

**What needs to be built:**
- Split current `research_analyst.py` into `data_analyst.py` + `thesis_builder.py`
- Thesis Builder is pure LLM reasoning over structured data (no tools)
- Add peer comparison tool (pull fundamentals for 3-4 sector peers)

---

### Desk 3: Risk Desk

**Purpose:** Independent risk authority. Reports to the CIO, not the PM. Has kill authority over trades.

**Agent 3A — Macro Regime Analyst**
- Classifies current macro regime: EXPANSION / LATE_CYCLE / CONTRACTION / RECOVERY
- Computes regime-conditional expected returns for the proposed tickers
- Identifies tail risks and scenario analysis
- Uses: `fred_client`, `quant/regime.py`, `quant/computations.py`
- Output: Regime classification + confidence + risk narrative

**Agent 3B — Position Risk Manager**
- Runs the hard risk gates (ENFORCED, not advisory):
  - Max position size: 5% of portfolio
  - Max sector concentration: 30%
  - Portfolio VaR budget: daily 95% VaR cannot exceed 2%
  - Correlation penalty: new position correlated > 0.7 with existing → size reduced
  - Drawdown circuit breaker: 5% DD → half size, 7.5% → no new, 10% → liquidate to 50% cash
  - Marginal VaR: adding this position must not increase portfolio VaR by more than 0.5%
- Uses: `quant/risk.py` (all functions), `quant/computations.py`
- Output: `{approved: bool, adjusted_size, reasons[], risk_metrics{}}`

**What exists today:** `risk_manager.py` does regime classification but risk checks are advisory. `quant/risk.py` has `pre_trade_risk_check()`, `compute_marginal_var()`, `drawdown_circuit_breaker()`, `check_sector_limits()`, `correlation_adjusted_size()` — all implemented and working.

**What needs to be built:**
- Split current `risk_manager.py` into `macro_regime_analyst.py` + `position_risk_manager.py`
- Wire `pre_trade_risk_check()` as a mandatory gate in the trade execution path
- Add trade blocking: if risk check returns `approved=false`, the trade is rejected with explanation
- Connect circuit breaker to portfolio state (query open trades for current drawdown)

---

### Desk 4: Portfolio Construction Desk

**Purpose:** Translate approved trade ideas into precisely sized positions with hedges.

**Agent 4A — Trade Structurer**
- Sets entry, stop, target levels using technical analysis (support/resistance, ATR-based stops)
- Sizes positions via Black-Litterman optimization within risk limits
- Adjusts for regime: smaller sizes in CONTRACTION, larger in EXPANSION
- Uses: `market_client`, `quant/optimizer.py`, `quant/risk.py`
- Output: Fully specified trade with entry_zone, stop_loss, take_profit, position_size_pct, risk_reward_ratio

**Agent 4B — Hedge Architect**
- Designs factor-neutral hedge baskets to offset unintended exposures
- Recommends specific options hedges (puts for downside, collars for income)
- Tail risk protection: VIX calls, put spreads on SPY/QQQ
- Uses: `quant/factors.py`, `quant/options_analytics.py`, `market_client`
- Output: Hedging recommendations with specific instruments, strikes, costs

**What exists today:** `portfolio_strategist.py` does trade structuring AND hedging in one agent. `quant/optimizer.py` (Black-Litterman, mean-variance) and `quant/options_analytics.py` (BSM, Greeks) exist.

**What needs to be built:**
- Split current `portfolio_strategist.py` into `trade_structurer.py` + `hedge_architect.py`
- Wire B-L optimizer into the Trade Structurer (currently called manually via API)
- Hedge Architect needs options pricing tools (already in `quant/options_analytics.py`)

---

### Desk 5: CIO / Synthesis Desk

**Purpose:** Final sign-off. Produces the intelligence memo and makes the go/no-go call.

**Agent 5A — Memo Writer**
- Produces the final intelligence memo with executive summary, full analysis (800-1500 words), and key findings
- Every paragraph cites specific numbers from the research data
- Pure LLM reasoning over accumulated pipeline context
- Output: `{title, executive_summary, analysis, key_findings[]}`

**Agent 5B — Decision Gate**
- Makes the final go/no-go recommendation based on:
  - Conviction threshold (>= 75 for BUY/SELL, >= 50 for WATCH)
  - Risk desk approval status
  - Regime alignment (is the macro environment supportive?)
  - Portfolio capacity (do we have room for this position?)
- Output: `{decision: "GO" | "NO-GO" | "WATCH", reason, confidence}`

**What exists today:** `cio_synthesizer.py` writes the memo. No decision gate exists — every analysis produces trade ideas regardless of whether they pass risk checks.

**What needs to be built:**
- Split current `cio_synthesizer.py` into `memo_writer.py` + `decision_gate.py`
- Decision Gate is mostly logic, not LLM — checks thresholds programmatically
- Wire the decision into the trade-taking flow (frontend shows GO/NO-GO badge)

---

### Desk 6: Scorecard & P&L Desk

**Purpose:** The feedback loop. Measures whether signals make money and adjusts the system accordingly.

**Agent 6A — Signal Scorer**
- Evaluates every past signal at 1-day, 5-day, and 20-day intervals
- Computes per-desk: hit rate, IC (information coefficient), ICIR, average P&L
- Tracks signal decay over time (does the edge diminish?)
- Uses: `quant/signal_validation.py`, `quant/performance.py`, `market_client`
- Output: Scorecard per desk and per ticker

**Agent 6B — Attribution Analyst**
- Decomposes portfolio P&L into:
  - Factor returns (beta, momentum, value, size) — "would an ETF have done this?"
  - Specific/alpha returns — "did our stock picking add value?"
  - Per-desk contribution — "which desk generated the most alpha?"
- Adjusts desk weights based on IC scores (high IC → more influence)
- Uses: `quant/factors.py`, `quant/performance.py`, trade history
- Output: Attribution report with desk-level P&L decomposition

**What exists today:** `quant/signal_validation.py` has IC, ICIR, hit rate, alpha decay functions — all implemented but never called. `quant/performance.py` has full performance metrics. `quant/factors.py` has factor decomposition. The math is there; the wiring is not.

**What needs to be built:**
- `SignalScoreRecord` model to persist scores at 1d/5d/20d
- Scoring job that runs daily (evaluates all signals older than 1d/5d/20d)
- Attribution endpoint that decomposes P&L
- Desk weight adjustment mechanism (store weights, update based on IC)
- Frontend: Scorecard page showing per-desk accuracy and P&L contribution

---

## 4. WHAT EXISTS vs WHAT NEEDS TO BE BUILT

### Exists and Can Be Reused As-Is

| Component | File | Used By |
|---|---|---|
| FRED macro data | `data/fred_client.py` | Desk 1 (Scanner), Desk 3 (Regime) |
| Yahoo Finance market data | `data/market_client.py` | All desks |
| NewsAPI + Finnhub | `data/news_client.py` | Desk 1 (Scanner), Desk 2 (Data Analyst) |
| SEC EDGAR client | `data/sec_client.py` | Desk 1 (Scanner), Desk 2 (Data Analyst) |
| Alpha Vantage technicals | `data/alpha_vantage_client.py` | Desk 2 (Data Analyst) |
| Firecrawl web search | `data/firecrawl_client.py` | Desk 2 (Data Analyst) |
| VADER sentiment NLP | `agents/nlp/sentiment.py` | Desk 2 (Data Analyst) |
| EWMA covariance | `quant/risk.py` | Desk 3 (Position Risk), Desk 4 (Trade Structurer) |
| VaR / CVaR | `quant/risk.py` | Desk 3 (Position Risk) |
| Sector limits | `quant/risk.py` | Desk 3 (Position Risk) |
| Drawdown circuit breaker | `quant/risk.py` | Desk 3 (Position Risk) |
| Correlation adjusted sizing | `quant/risk.py` | Desk 3 (Position Risk) |
| Marginal VaR | `quant/risk.py` | Desk 3 (Position Risk) |
| Pre-trade risk check | `quant/risk.py` | Desk 3 (Position Risk) |
| HMM regime detection | `quant/regime.py` | Desk 3 (Macro Regime) |
| Regime conditional returns | `quant/regime.py` | Desk 3 (Macro Regime) |
| Black-Litterman optimizer | `quant/optimizer.py` | Desk 4 (Trade Structurer) |
| Mean-variance optimizer | `quant/optimizer.py` | Desk 4 (Trade Structurer) |
| BSM + Greeks | `quant/options_analytics.py` | Desk 4 (Hedge Architect) |
| Factor decomposition | `quant/factors.py` | Desk 6 (Attribution) |
| IC / ICIR / hit rate | `quant/signal_validation.py` | Desk 6 (Signal Scorer) |
| Performance metrics | `quant/performance.py` | Desk 6 (Attribution) |
| Backtester | `quant/backtester.py` | Desk 6 (Signal Scorer) |
| Trade evaluation | `quant/backtesting.py` | Desk 6 (Signal Scorer) |
| Correlation matrix | `quant/computations.py` | Desk 3, Desk 4, Frontend |
| Drawdown computation | `quant/computations.py` | Desk 3, Frontend |
| Volatility metrics | `quant/computations.py` | Desk 2, Frontend |
| All DB models | `db/models.py` | All desks |
| All repositories | `db/repositories.py` | All desks |
| Clerk auth | `auth.py` | All endpoints |
| SSE streaming | `main.py` | Frontend analysis page |
| All 20+ API endpoints | `main.py` | Frontend |
| Frontend: 6 pages, 11 components | `frontend/` | User interface |

### Needs Refactoring (Split Existing Agents)

| Current Agent | Splits Into | Desk |
|---|---|---|
| `research_analyst.py` | `data_analyst.py` + `thesis_builder.py` | Desk 2 |
| `risk_manager.py` | `macro_regime_analyst.py` + `position_risk_manager.py` | Desk 3 |
| `portfolio_strategist.py` | `trade_structurer.py` + `hedge_architect.py` | Desk 4 |
| `cio_synthesizer.py` | `memo_writer.py` + `decision_gate.py` | Desk 5 |
| `query_interpreter.py` | Absorbed into Desk 1 Scanner or kept as pipeline entry | Desk 1 |

### Needs to Be Built New

| Component | Desk | Complexity |
|---|---|---|
| Universe Scanner agent | Desk 1 | Medium — wraps existing data clients with anomaly detection |
| Signal Ranker agent | Desk 1 | Medium — regime-conditional filtering, ranking logic |
| Thesis Builder agent | Desk 2 | Low — pure LLM reasoning, no new tools |
| Decision Gate agent | Desk 5 | Low — mostly programmatic threshold checks |
| Signal Scorer agent | Desk 6 | Medium — wires existing `signal_validation.py` + new DB model |
| Attribution Analyst agent | Desk 6 | Medium — wires existing `factors.py` + `performance.py` |
| `WatchlistRecord` model | Desk 1 | Low — simple DB model + CRUD |
| `SignalScoreRecord` model | Desk 6 | Low — stores 1d/5d/20d scores |
| `DeskWeightRecord` model | Desk 6 | Low — stores per-desk IC-derived weights |
| Enforced risk gate in trade path | Desk 3 | Low — wire existing `pre_trade_risk_check()` |
| Portfolio positions endpoint | All | Low — aggregate open trades + live prices |
| Nightly screening cron | Desk 1 | Medium — scheduled job runner |
| Scorecard frontend page | Desk 6 | Medium — new page with per-desk metrics |

---

## 5. PHASED BUILD PLAN

### Phase 1 — Foundation (COMPLETE)

Everything in the "Exists and Can Be Reused" table above. 5-agent pipeline, 5 data clients, 8 quant modules, 10 DB models, 20+ endpoints, 6 frontend pages. Deployed on Railway.

### Phase 2 — Desk Architecture Migration

**Goal:** Refactor the 5-agent pipeline into the 6-desk / 12-agent architecture without breaking the existing API surface.

**Step 1: Split existing agents (no new functionality, same outputs)**
- Research Analyst → Data Analyst + Thesis Builder
- Risk Manager → Macro Regime Analyst + Position Risk Manager
- Portfolio Strategist → Trade Structurer + Hedge Architect
- CIO Synthesizer → Memo Writer + Decision Gate
- Update orchestrator to chain desks sequentially

**Step 2: Enforce risk gates**
- Wire `pre_trade_risk_check()` into `/api/portfolio/trade` as a mandatory gate
- Add drawdown monitoring to circuit breaker (query current open trade P&L)

**Step 3: Build Desk 6 — Scorecard**
- `SignalScoreRecord` model
- Daily scoring job (evaluate past signals at 1d/5d/20d)
- Attribution endpoint using existing factor decomposition
- Scorecard API endpoints

**Step 4: Build Desk 1 — Screening**
- `WatchlistRecord` model + CRUD
- Universe Scanner agent (anomaly detection across ticker universe)
- Signal Ranker (regime-conditional filtering)
- Manual scan trigger endpoint
- Wire into morning report

### Phase 3 — Intelligence & Scale

- FinBERT sentiment upgrade (replace VADER)
- Adaptive desk weights (auto-adjust based on IC scores from Desk 6)
- Nightly automated screening (cron job)
- Portfolio positions aggregation + live P&L
- Scorecard frontend page
- Event-driven triggers (8-K filed → auto-analyze)

### Phase 4 — Execution & Attribution

- Paper trading via Alpaca API
- Fill tracking and slippage measurement
- Full P&L attribution (factor vs alpha vs noise)
- Signal decay monitoring and model retirement
- Performance analytics dashboard

---

## 6. CRITICAL DESIGN PRINCIPLES

1. **Risk desk has kill authority.** The Position Risk Manager's `approved: false` blocks trade execution. No PM override. This is what separates a fund from a newsletter.

2. **The feedback loop is non-negotiable.** Every signal gets scored. Every desk gets measured. Weight adjustment is automatic. Without this, the system can't learn.

3. **Quant modules stay LLM-free.** All math in `quant/` uses numpy/scipy — deterministic, testable, auditable. LLMs reason; math computes.

4. **Agents are specialists, not generalists.** Each agent does one thing well. Data Analyst gathers data. Thesis Builder writes the thesis. They don't cross responsibilities.

5. **Regime awareness is pervasive.** Every desk considers the macro regime. A bullish signal in CONTRACTION gets dampened. A bearish signal in EXPANSION gets scrutinized. Regime is not a filter — it's a lens.

6. **Conservative API usage.** Every data client has TTL caching. Free-tier rate limits are respected. A single careless loop can blind the platform for 24 hours.

---

*This document is the single source of truth for the Alpha Engine architecture. Version 1.0 (initial spec) is superseded. All new development follows the desk model defined here.*
