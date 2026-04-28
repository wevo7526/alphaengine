# Alpha Engine — Architecture & Computational Rigor

A walking tour of how the platform is built, paired so each technical paragraph is followed by a one-sentence plain-English translation. Read it top-to-bottom and you'll be able to defend the system in front of a hedge fund quant, a software architect, or your grandmother.

---

## 1. The 30,000-foot view

Alpha Engine is a multi-agent AI system that mimics how a real multi-strategy hedge fund desk operates. A query goes in; a structured intelligence memo comes out; the user can accept individual trade ideas with one click; positions mark to market in real time; the system scores its own past predictions and feeds that track record back into the next analysis.

> **Plain English:** You ask a question, five AI specialists collaborate to answer it, the system tracks how right it was last time, and you can paper-trade the recommendations with one click.

Architecturally there are three layers stacked vertically. The **data layer** pulls from six external sources (FRED for macro, Yahoo Finance for prices, NewsAPI + Finnhub for news, SEC EDGAR for filings, Alpha Vantage for technicals). The **agent layer** is five LLM-driven desks orchestrated through LangGraph that read from the data layer, reason in turn, and produce a structured memo. The **quantitative layer** is pure numpy/scipy math — no LLM — that handles risk, regime detection, optimization, factor analysis, and signal validation.

> **Plain English:** Three floors — bottom floor fetches data, middle floor uses AI to reason about it, top floor does the math the AI can't be trusted to do.

---

## 2. The five-desk agent pipeline

The agents run in a strict sequence, each receiving the accumulated state from prior agents. This is built on **LangGraph**, a library that lets you wire LLM agents into a deterministic state machine instead of letting them call each other ad-hoc.

> **Plain English:** Five AI agents pass a folder down a hallway in fixed order, each adding their findings before handing it to the next.

### Desk 1 — Query Interpreter

Takes the user's freeform query (e.g., "what's my best play around the Strait of Hormuz reopening?") and converts it into a structured `AnalysisPlan` containing detected intent (`thematic_research`, `ticker_analysis`, `risk_assessment`, `portfolio_review`, `morning_briefing`), tickers to analyze, themes, and explicit data requests for the next desk. Pure LLM reasoning, no tool calls.

> **Plain English:** Reads the question and turns it into a checklist for the rest of the team.

### Desk 2 — Research Analyst

The data-gathering desk. It has 18 tools spanning macro snapshots, price history, fundamentals, options chains, news (NewsAPI + Finnhub), SEC filings (8-K, 10-K, 10-Q full-text search, insider trades), web search via Firecrawl, RSI/MACD technicals, and FinBERT-style news sentiment scoring. It executes the data requests from Desk 1 and produces a `ResearchData` blob containing a narrative `data_summary` plus structured ticker-level data.

> **Plain English:** The intern who actually pulls the data — earnings, news, insider trading filings, technical indicators — and writes up what they found.

### Desk 3 — Risk Manager + Position Risk Gate

The risk desk has two halves. **Desk 3A** is an LLM agent that reads the research and classifies the macro regime (`expansion`, `late_cycle`, `contraction`, `recovery`), enumerates risk factors with `severity` and `category` tags, and assigns an `overall_risk_level`. **Desk 3B** is `desk3_position_risk.py` — pure code — that runs `evaluate_trade_gate()` against any proposed trade: it checks position size, sector concentration, drawdown circuit breaker, and correlation with existing book.

> **Plain English:** One half thinks about big-picture risks and writes about them; the other half is a hard rulebook that says "you can't put 80% of the portfolio in one sector."

### Desk 4 — Portfolio Strategist

Constructs the actual trade ideas. Required output: 5 trade ideas ranked by conviction (must be ≥50), each with ticker, direction (`bullish`/`bearish`/`neutral` × strong/moderate), `entry_zone`, `stop_loss`, `take_profit`, `position_size_pct` (capped at 5%), `risk_reward_ratio` (must be >1.5:1), thesis, catalysts, risks, time horizon. Plus 5 hedging recommendations and a `portfolio_positioning` label.

> **Plain English:** Turns the research into concrete trades with specific entry, stop-loss, and target prices — like a trader writing tickets.

### Desk 5 — CIO Synthesizer + Decision Gate

**Desk 5A** writes the executive memo: title, executive_summary (3-4 sentences), 4-6 paragraphs of analysis with mandatory quantitative citations, and 5 key findings. It now also receives the user's track record — hit rates, IC, by-conviction-bucket performance — and is instructed to calibrate conviction language against those numbers. **Desk 5B** is `desk5_decision_gate.py` — pure code — that programmatically assigns GO / WATCH / NO-GO based on top conviction (≥75 = GO eligible), regime alignment, and risk level (extreme = NO-GO regardless).

> **Plain English:** The Chief Investment Officer reads everyone's work, writes the memo, and a separate rule-based gate stamps it GO, WATCH, or NO-GO.

### Desk 6 — Scorer (offline, runs on demand)

After signals age, this desk pulls forward prices at 1-day, 5-day, and 20-day intervals from when the memo was written, computes direction-adjusted returns, and writes `SignalScoreRecord` rows. From these it builds the **scorecard**: hit rate per horizon, Information Coefficient (Spearman correlation between conviction and forward return), and breakdown by conviction bucket. The CIO uses this to calibrate next time — a closed feedback loop.

> **Plain English:** Looks at what happened to past predictions, scores them, and feeds the scorecard back into the next analysis so the system gets smarter over time.

---

## 3. The streaming UX

When the user calls `/api/analyze/stream`, the backend opens a Server-Sent Events (SSE) connection. Each agent's tool calls and tool results are surfaced live via `DeskStreamCallback`, so the frontend can show "Research Desk: get_fundamentals(AAPL) → P/E 32.5x" as it happens. This is what makes the system feel like watching a trading floor instead of waiting for a black box.

> **Plain English:** The frontend gets a live feed of every move the AI agents make — like watching them work in real time, not waiting for a result to pop out.

If the client disconnects, the active background tasks are cancelled so we don't burn Anthropic API credits on an analysis nobody's watching. There's also a 90-second middleware timeout on every non-streaming endpoint to prevent stuck dependencies from wedging the UI in perpetual loading.

> **Plain English:** Close the browser and the AI stops working immediately so we don't waste money — and any request that takes too long times out cleanly.

---

## 4. The quantitative layer (pure math, no LLM)

This is where the computational rigor lives. Eight modules in `backend/quant/` provide deterministic, auditable, reproducible math.

### 4.1 Risk Management — `quant/risk.py`

**EWMA Covariance.** We don't use a flat sample covariance because recent volatility regimes matter more than ancient history. Exponentially Weighted Moving Average with halflife=63 trading days (~1 quarter) means data from 63 days ago has half the weight of today's data. The result is a 252-day-annualized covariance matrix that adapts to the current vol regime.

> **Plain English:** Recent market behavior matters more than what happened a year ago, so we weight recent days heavier when measuring how risky each stock is.

**Parametric VaR.** Given a portfolio's weights and the EWMA covariance, we compute `var = z × portfolio_vol × √horizon` where `z = 1.645` for 95% confidence. This tells you the worst expected daily loss at a given confidence level. Reported in both percentage and dollar terms against a portfolio base of $100k.

> **Plain English:** "How much could you lose tomorrow on a really bad day?" — that's VaR.

**Historical CVaR (Expected Shortfall).** Instead of just the cutoff, CVaR averages the actual returns *below* the VaR threshold. This is more honest about tail risk because it tells you the average size of disaster days, not just the threshold of a disaster. Requires 20+ observations.

> **Plain English:** When a really bad day happens, how bad is it on average? That's CVaR — VaR's more pessimistic cousin.

**Sector concentration check.** Hard cap at 30% per sector. Walks through positions, sums weights by sector, flags violations.

> **Plain English:** Don't put more than 30% of the portfolio in any one industry.

**Drawdown circuit breaker.** Tiered response based on portfolio drawdown: under 5% is normal sizing; 5-7% reduces new positions to half size; 7-10% blocks all new positions; over 10% triggers liquidation back to 50% cash.

> **Plain English:** When the portfolio is down a lot, the system gradually stops you from making it worse.

**Correlation-adjusted sizing.** Before sizing a new position, computes its average correlation with existing book and dampens size accordingly. A new long that's 0.9 correlated with an existing 5% long contributes far more risk than its weight suggests.

> **Plain English:** Don't load up on five stocks that all move together — that's secretly one big position.

**Marginal VaR.** Measures how much portfolio VaR changes if you add a proposed position. Used (in theory) as a final check in the trade gate.

> **Plain English:** "If I add this trade, how much riskier does the whole portfolio get?"

### 4.2 Regime Detection — `quant/regime.py`

**Hidden Markov Model.** Three latent states (`risk_on`, `transition`, `risk_off`) with full-covariance Gaussian emissions, fit to standardized macro features (VIX, BBB credit spreads, 10Y-2Y yield curve) over a 500-day window. After fitting, regimes are auto-labeled by VIX cluster mean — lowest VIX cluster gets `risk_on`, highest gets `risk_off`. Refits daily.

> **Plain English:** A statistical model that watches three market indicators and says "we're in a calm regime / nervous regime / panicked regime" with probabilities, not just a label.

**Rule-based fallback.** If `hmmlearn` isn't installed or fitting fails, falls back to deterministic thresholds (VIX < 18 + tight spreads + positive yield curve = `risk_on`; VIX > 28 OR wide spreads OR inverted curve = `risk_off`; else `transition`). The fallback is documented as a known weakness — those thresholds are heuristic, not backtested.

> **Plain English:** If the fancy AI model breaks, we fall back to simple if-then rules so the system always returns *something*.

**Conditional returns.** For any given ticker, slices its historical returns by what regime was active each day, then reports annualized return, vol, % positive days, and observation count per regime. Lets you say "SPY has historically averaged +14% annualized in `risk_on` and -8% in `risk_off`."

> **Plain English:** Tells you how a stock has historically performed in good vs. bad market conditions.

### 4.3 Performance Analytics — `quant/performance.py`

Standard institutional metrics: Sharpe ratio (excess return / vol), Sortino (excess return / *downside* vol — penalizes only losing days), Calmar (annualized return / max drawdown), max drawdown, drawdown duration, alpha & beta vs. SPY, rolling Sharpe windows. All correctly annualized assuming 252 trading days.

> **Plain English:** All the standard "is this strategy actually good?" numbers a portfolio manager would ask for.

### 4.4 Backtester — `quant/backtester.py`

Walk-forward simulation over a user-defined ticker set and time period. Generates signals from RSI + MA crossover rules, opens positions sized by `max_position_size` cap, applies 5bp slippage on entry and exit, books P&L when stops or targets are hit, and benchmarks the equity curve against SPY. Reports Sharpe, Sortino, max drawdown, win rate, profit factor, and trade-by-trade detail.

> **Plain English:** "If I had run this strategy on the last year of data, what would have happened?" — with realistic frictions like trading costs.

### 4.5 Factor Analysis — `quant/factors.py`

OLS regression of asset returns on benchmark returns to extract beta (market exposure) and alpha (excess return). Single-factor live in the API, multi-factor (Fama-French 5 + momentum) implemented but not yet exposed. Reports R² and t-statistics on alpha so significance can be flagged.

> **Plain English:** Decomposes returns into "you got this just for being in the market" vs. "this is real skill" — and tells you how confident we are in the skill number.

### 4.6 Signal Validation — `quant/signal_validation.py`

**Information Coefficient.** Spearman rank correlation between conviction levels and realized forward returns. IC > 0.05 is "useful," IC > 0.10 is "strong," IC < 0 means the signals are inversely predictive (selling when they say buy would make money).

> **Plain English:** Measures whether high-conviction picks actually do better than low-conviction picks — the gold-standard test that the AI's confidence scores are real.

**Hit rate by conviction bucket.** Slices past signals into low / medium / high conviction buckets and reports the win rate of each. A well-calibrated system has monotonically increasing hit rates as conviction rises.

> **Plain English:** Are your "I'm 90% sure" picks actually winning more often than your "50/50" picks?

**Alpha decay.** Computes IC at multiple horizons (1d, 2d, 5d, 10d, 21d) to see how fast the signal advantage fades. Useful for setting trade durations.

> **Plain English:** How long after the AI says "buy" is its prediction still useful — hours, days, weeks?

### 4.7 Portfolio Optimization — `quant/optimizer.py`

**Mean-variance.** Classical Markowitz: maximize the Sharpe ratio subject to weights summing to 1, long-only with 20% per-position cap, solved via SLSQP (a constrained nonlinear optimizer in scipy).

> **Plain English:** Math that finds the mix of positions giving the best return per unit of risk.

**Black-Litterman.** Starts from a market-implied prior, then incorporates the agent's `trade_idea` directions and convictions as views with confidence-weighted uncertainty (Omega matrix). Produces posterior expected returns that blend market consensus with our specific views. This is the framework Goldman Sachs popularized in the 1990s.

> **Plain English:** Combines "what does the market think?" with "what does our research think?" weighted by how confident we are in each view.

**Rebalance trade generation.** Given current weights and target weights, produces the buy/sell trade list with notional dollar amounts.

> **Plain English:** "Here are the actual trades you'd need to execute to get from where you are to where the optimizer says you should be."

### 4.8 Options Analytics — `quant/options_analytics.py`

Black-Scholes-Merton pricing, all five Greeks (delta, gamma, theta, vega, rho), put/call ratio, IV skew (puts vs. calls implied vol), unusual activity detection (volume / open interest ratios > 2× normal), max pain calculation, and ATM straddle pricing for market-implied expected move.

> **Plain English:** Everything an options trader would compute by hand — fair value, sensitivities to price, time, and volatility, and which contracts are seeing unusual activity.

---

## 5. The data layer

Six clients in `backend/data/`, each with TTL caching tuned to its rate limit:

| Source | What | Cache TTL | Why this TTL |
|---|---|---|---|
| FRED | 13 macro indicators (VIX, fed funds, yield curve, CPI, etc.) | 1 hour | Macro updates daily at most |
| Yahoo Finance | OHLCV, fundamentals, options chains | 15 min prices, 1 hour fundamentals | Free / unlimited but courteous |
| NewsAPI | News articles | 30 min | 100/day limit — TIGHT |
| Finnhub | Pre-scored sentiment + company news | 15 min | 60/min limit |
| SEC EDGAR | 8-K, 10-K, 10-Q full text, insider trades, 13F | None (per-call) | 100/month limit — TIGHTEST |
| Alpha Vantage | Pre-computed RSI, MACD, Bollinger | 4 hours | 25/day limit, daily-bar indicators |

> **Plain English:** Six external APIs feed the system; each one caches results aggressively because most of them have tight free-tier limits and we'd go blind if we burned through them.

Free-tier rate limits drove the architecture: every client caches by ticker + parameter so that when two agents need the same data within minutes, the second call is free. This is how five concurrent agents run on free APIs without going dark.

> **Plain English:** When two agents need the same data, only one actually fetches it — the other gets a copy from the cache.

---

## 6. Persistence

**Postgres** (Railway-hosted production, SQLite locally) storing 13 ORM models: intelligence memos, trades, portfolio positions, portfolio snapshots, factor exposures, regime states, macro snapshots, signal scores, watchlist, morning reports, backtest runs/results, and (legacy) scan runs/findings. Async SQLAlchemy with asyncpg driver, connection pool sized for 4 uvicorn workers.

> **Plain English:** All the analyses, trades, and scores are stored in a database so they survive across sessions.

**TIMESTAMPTZ schema migration.** Every `DateTime` column declares `timezone=True` and the startup migration runs `ALTER COLUMN ... TYPE TIMESTAMPTZ USING column AT TIME ZONE 'UTC'` per-column with try/except per statement. Idempotent — safe to run on every startup. Existing rows are tagged as UTC since that's what the app has always written.

> **Plain English:** Every timestamp in the database knows what timezone it's in, so we don't get bugs when the system crosses time zones.

---

## 7. Auth & multi-tenancy

**Clerk JWT** verification via JWKS public-key rotation (`PyJWKClient` with 1-hour cache). Production fails closed — if `CLERK_ISSUER` isn't set, every protected route returns 401 instead of trusting unverified tokens. Dev mode allows unverified decoding for local testing.

> **Plain English:** Every API request must carry a verified user ID from Clerk; if the auth config is missing in production, requests fail safely instead of letting anyone in.

Every user-scoped query filters by `user_id`. Trades, memos, scorecards, positions — all filtered. Repository methods that don't take `user_id` are documented as a known weakness; the audit identified five endpoints (backtest runs/results, portfolio risk, portfolio backtest) that previously leaked across users — all patched.

> **Plain English:** User A can never see User B's trades or analyses, and every endpoint that touches user data was audited for cross-user leaks.

---

## 8. The Human-In-The-Loop trading flow

This is the operational loop that makes the system feel like a real desk.

1. User runs an analysis → memo materializes with 5 trade ideas, each with entry / stop / target / R:R.
2. User clicks **"Take Trade @ Market"** on any idea. Backend fetches the current market price via `market_client.get_fundamentals()` and persists a `TradeRecord` with the live entry price. UI confirms `Filled @ $X.XX`.
3. The Position Risk Gate (Desk 3B) runs first: if it returns `BLOCK`, the trade is rejected with a 422 and the user sees the reasons. (Note: this is on the to-do list to wire as a true block; today it's still advisory.)
4. Open positions on `/portfolio` mark to market on every page load via concurrent `get_fundamentals` calls. Per-position weighted-avg entry, current price, unrealized P&L %, and unrealized P&L $.
5. Dashboard mini-card surfaces aggregated portfolio P&L when the user has open trades.
6. User clicks **"Close @ Market $X.XX"** — system fetches the current price, prefills the input, one click closes at market. Or the user types a custom exit price.
7. Closed trades flow into the scorer. After 1d / 5d / 20d, the system measures direction-adjusted returns and writes `SignalScoreRecord` rows. Aggregate scorecard updates.
8. The next analysis pulls the user's scorecard and feeds it into the CIO Synthesizer's calibration prompt — high-IC conviction buckets reinforce, low-IC buckets dampen.

> **Plain English:** Run analysis → click to take trade at market price → portfolio shows live profit/loss → click to close at market price → system scores how the trade turned out → next analysis is calibrated against your real track record.

No real money ever touches the system. This is paper trading by design. Everything else — the agents, the risk gates, the scoring, the calibration loop — operates exactly as it would for live trading.

> **Plain English:** It does everything a real fund does except actually move dollars — perfect for proving the concept without taking real risk.

---

## 9. Frontend architecture

**Next.js 16 with App Router**, React 19, Tailwind v4, Recharts for charts, Clerk for auth UI, lightweight-charts for price candles. Dark theme throughout. Six pages:

- **Dashboard** (`/`) — macro snapshot, regime card, portfolio P&L mini-card (when open positions exist), morning briefing, recent analyses
- **Analysis** (`/analysis`) — freeform query input, live SSE-streamed agent activity feed, structured memo render with click-to-take-trade buttons
- **Portfolio** (`/portfolio`) — tabs for Positions, Scorecard, Attribution, Trade Journal, Analyses, Backtest, Factors. Live mark-to-market. Flush-positions button.
- **Risk** (`/risk`) — VaR / CVaR / vol / sector exposure / circuit breaker / correlation heatmap / regime probabilities / regime-conditional returns
- **Settings** (`/settings`) — live system status from `/api/system/info`: env, DB dialect, Clerk issuer status, per-API-key configured flags, risk parameters in effect
- **Sign-in / Sign-up** (Clerk components)

> **Plain English:** Six screens covering everything from "what's the market doing?" to "how are my positions doing?" to "is the backend healthy?" — all dark-mode and built on the latest React.

API client (`lib/api.ts`) attaches Clerk Bearer tokens to every request, has a 45s default timeout with `AbortController`, and serializes errors with helpful detail. Frontend type-safety is enforced — `tsc --noEmit` passes clean before any commit.

> **Plain English:** Every API call is automatically signed with the user's login token, gives up after 45 seconds, and can't ship if TypeScript finds a type bug.

---

## 10. Observability & resilience

**Structured logging** with request IDs threaded through `RequestIdMiddleware` so every log line in a request's lifecycle is grepable by ID. **Health endpoint** (`/api/health`) probes the DB and reports `degraded` if startup errors exist. **Readiness endpoint** (`/api/ready`) returns 503 in degraded states for orchestrator routing. **Request timeout middleware** (`infra/timeout.py`) wraps every non-streaming handler in `asyncio.wait_for(90s)` and returns 504 if exceeded — guarantees no handler can wedge the UI in perpetual loading. SSE endpoints (`/api/analyze/stream`) are explicitly exempted because they're long-lived by design.

> **Plain English:** Every log line is tagged so you can trace one request's journey, the health check tells you what's broken, and no handler can hang for more than 90 seconds.

LLM agents have per-stage timeouts: 30s for the interpreter, 180s for research (it pulls a lot of data), 90s for risk and strategy each, 120s for the CIO. If any stage times out, the orchestrator constructs a degraded memo from prior outputs instead of failing the whole pipeline.

> **Plain English:** Each AI specialist has its own deadline; if one runs late, we still ship the best memo possible from what the others produced.

---

## 11. The deployment story

**Backend** runs on Railway in a Docker container, Python 3.11, single uvicorn worker (multi-worker turned out to overload Railway's resource limits — see commit `d0afee7`). Postgres is a Railway plugin, automatic `DATABASE_URL` injection. Environment variables for all API keys + Clerk. `Procfile` defines the start command.

> **Plain English:** Push to GitHub → Railway redeploys automatically with one Docker container, one Postgres database, and environment variables for all the API keys.

**Frontend** also on Railway, Next.js standalone build, public env vars for Clerk's publishable key and the backend URL. CORS configured server-side.

> **Plain English:** The frontend is its own deployment that talks to the backend over the public internet, configured at build time.

`git push origin main` triggers both redeploys. The TIMESTAMPTZ migration runs idempotently on every backend startup, so deploys are zero-downtime against schema changes.

> **Plain English:** Every push to main automatically deploys both halves; database schema changes are safe to ship because the migration only runs what hasn't already been done.

---

## 12. What makes this defensible

The core IP isn't any one piece — it's the **integration**. Specifically:

1. **A real research desk doesn't have one AI; it has specialists who pass work in order.** Five agents with bounded tools and structured outputs is the architectural choice that prevents a monolithic LLM from hallucinating its way through a memo.
2. **Pure-math layer separated from LLM layer** — the risk numbers, factor regressions, and regime probabilities are deterministic numpy/scipy. The LLM never touches the math; it only reads the math's output. This is what makes it auditable.
3. **Closed feedback loop** — past predictions get scored, scorecard feeds back into calibration. The system learns from itself in a way that's measurable (IC, hit rate by conviction bucket).
4. **Conservative API usage** — every external call is cached by TTL tuned to the source's rate limit. We can run five concurrent agents on free-tier APIs because the second call for the same data is always a cache hit.
5. **Hard risk gates** — sector concentration, drawdown circuit breaker, position-size caps, correlation-adjusted sizing all execute as deterministic code, not LLM judgment calls.

> **Plain English:** The defensibility isn't any single feature — it's that the AI does what AI is good at (reading and reasoning), the math does what AI is bad at (precise calculations), and the system grades itself so it can improve.

---

## 13. What's intentionally not in scope

- **No real-money trading** — paper-trading only. Adding broker integration (Alpaca paper or live) is a one-week addition but kept out for the demo.
- **No multi-user portfolio sharing** — each user's data is strictly siloed.
- **No machine learning model fine-tuning** — agents use Anthropic's Claude with structured prompts; we don't train our own models.
- **No high-frequency or intraday execution** — analysis pipeline takes 30s-3min, designed for swing trading horizons (days to weeks), not microseconds.

> **Plain English:** This isn't a high-frequency trading bot or a brokerage — it's a research and decision-support system that stops short of moving real money.

---

## 14. The 50,000-foot view

If you walked into a multi-strategy hedge fund tomorrow, you'd find five teams: a Macro desk, a Fundamental desk, a Quant desk, a Risk desk, and a CIO who synthesizes everyone's pitches into the firm's positions. Alpha Engine has built that exact structure in software. The AI layer reasons; the math layer measures; the data layer feeds; the scoring layer grades; the user is the human-in-the-loop who decides which trades to take. Five days of effort and a Railway deployment turn into a hedge fund operating system that does everything except handle real dollars.

> **Plain English:** It's a real hedge fund desk, in software, that does everything a real desk does except hold real money.

---

## Glossary (quick reference)

- **VaR** (Value at Risk): Maximum expected daily loss at a given confidence level (usually 95%).
- **CVaR** (Conditional VaR / Expected Shortfall): Average loss on the worst 5% of days. More honest about tails than VaR.
- **EWMA**: Exponentially Weighted Moving Average. Recent data weighted heavier than old data.
- **Sharpe Ratio**: Excess return per unit of total volatility. Higher = better risk-adjusted return.
- **Sortino Ratio**: Sharpe but only penalizes downside vol. More forgiving of upside swings.
- **HMM** (Hidden Markov Model): Statistical model with hidden states whose transitions and emissions are estimated from data. Used here for regime detection.
- **IC** (Information Coefficient): Rank correlation between predicted and realized returns. Standard test of signal quality.
- **Black-Litterman**: Bayesian portfolio optimization framework that combines a market prior with investor views weighted by confidence.
- **SSE** (Server-Sent Events): One-way streaming protocol from server to browser. Used here for live agent activity feeds.
- **JWKS**: JSON Web Key Set. The public keys an auth provider publishes so anyone can verify their JWT signatures.
- **TIMESTAMPTZ**: Postgres column type that stores UTC and a timezone offset together. Prevents timezone-confusion bugs.

> **Plain English:** Every acronym a quant or engineer might throw at you, with what it actually means.
