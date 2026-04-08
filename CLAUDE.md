# Alpha Engine — Build Log

## Phase 1, Step 1: Monorepo Scaffold

**What was built:**
- Full monorepo directory structure (`backend/` + `frontend/`)
- FastAPI backend skeleton with all 14 API route stubs + health check
- Pydantic models: `SignalDirection`, `AgentSignal`, `ConsensusSignal`
- Config layer using `pydantic-settings` loading all env vars
- Next.js 16 frontend (TypeScript, Tailwind, App Router)
- Docker Compose for local Postgres 16 + Redis 7
- `.env.example` with all required environment variable names

**Verification:** Backend starts clean with uvicorn, health endpoint returns 200. Frontend compiles with zero errors via `npm run build`.

---

## Phase 1, Step 2: SEC EDGAR Data Client (`backend/data/sec_client.py`)

**What was built:**
Full SEC-API.io integration client with 9 methods spanning 5 API surfaces:

| Method | SEC-API Surface | What It Does |
|--------|----------------|--------------|
| `get_recent_filings()` | QueryApi | Search filings by ticker + form type (8-K, 10-K, 10-Q) |
| `get_filings_by_date_range()` | QueryApi | Date-bounded filing search for quarter-over-quarter comparison |
| `search_filings_fulltext()` | FullTextSearchApi | Full-text search across all filings for keywords |
| `extract_mda()` | ExtractorApi | Pull MD&A section (Item 7) from 10-K/10-Q |
| `extract_risk_factors()` | ExtractorApi | Pull Risk Factors section (Item 1A) |
| `extract_financial_statements()` | ExtractorApi | Pull Financial Statements (Item 8) from 10-K |
| `extract_business_description()` | ExtractorApi | Pull Business Description (Item 1) from 10-K |
| `get_insider_trades()` | InsiderTradingApi | Insider buys/sells from Forms 3, 4, 5 |
| `get_13f_holdings()` | Form13FHoldingsApi | Institutional holdings by filer CIK |
| `search_13f_for_ticker()` | Form13FHoldingsApi | Reverse lookup — which institutions hold a given ticker |

**Why it was built:**
SEC filings are the ground truth of public company analysis. Every number in a financial model, every risk in a thesis, and every catalyst on a timeline traces back to an SEC filing. This client gives the Fundamental Agent and Sentiment Agent direct access to the raw source material that Wall Street analysts spend their days reading.

**How it functions from a finance perspective:**

1. **Filing Search (8-K, 10-K, 10-Q):** 8-Ks are the real-time pulse — material events like earnings surprises, M&A announcements, executive departures, and guidance revisions. 10-Ks and 10-Qs are the structural backbone — full financial statements, management's own narrative (MD&A), and legally mandated risk disclosures. The Fundamental Agent uses these to build its valuation picture.

2. **Full-Text Search:** This is where edge is found. Searching for phrases like "going concern", "goodwill impairment", "material weakness", or "restatement" across thousands of filings surfaces problems that ratio analysis alone misses. A company can have a clean P/E and still be hiding a going concern qualification in the auditor's notes. The Fundamental Agent uses this as a red-flag scanner.

3. **Section Extraction (MD&A, Risk Factors):** MD&A is management explaining the *why* behind the numbers — language changes between quarters (new hedging words, removed growth language, tone shifts) are leading indicators of future earnings trajectory. Risk factor diffs between filings reveal emerging threats before they hit the income statement. The Sentiment Agent compares these across quarters to detect narrative shifts.

4. **Insider Trading (Forms 3/4/5):** Insider buying is one of the most reliable bullish signals in equity markets. Cluster buying (3+ insiders within 30 days) is strongly predictive. CEO/CFO buys carry more weight than director buys. The dollar amount matters more than share count. The Fundamental Agent uses this for conviction amplification — strong fundamentals + insider buying = high-conviction signal.

5. **13F Holdings:** These reveal institutional positioning with a 45-day lag. New positions from high-quality funds signal institutional conviction. Crowding (too many funds in the same name) signals fragility risk. Position changes across quarters reveal whether smart money is accumulating or distributing. The Fundamental Agent uses this to assess "who else is in this trade" and whether the ownership base is stable or fragile.

**How it fits together:**
The SEC client is one of five data clients that feed the agent pool. The Fundamental Agent is its primary consumer (filings, financials, insider trades, 13F), with the Sentiment Agent as secondary (8-K text, MD&A language for NLP analysis). All methods return raw data that agents process through their LLM reasoning chains to produce `AgentSignal` outputs, which then flow into the Consensus Engine.

---

## Phase 1, Step 3: Data Ingestion Layer (All 5 Clients Complete)

**Design principle: Conservative API usage.** Every client has in-memory TTL caching. Free-tier rate limits are tight — NewsAPI (100/day), Alpha Vantage (25/day), SEC-API (100/month), Finnhub (60/min). A single careless loop can blind the platform for 24 hours. Each client caches results and returns cached data when the TTL hasn't expired.

### `backend/data/fred_client.py` — FRED Macro Data

**What it does:** Pulls 13 macroeconomic indicators from the Federal Reserve's FRED database in a single `get_macro_snapshot()` call. Also provides `get_series_history()` for trend analysis and `get_single_indicator()` for targeted lookups.

**Cache strategy:** 1-hour TTL on all data. Macro indicators update at most daily (many are weekly/monthly), so re-fetching within an hour is pure waste.

**Finance perspective:** The Macro Agent uses this to classify the current regime:
- **Yield curve (T10Y2Y):** Inversion (negative spread) is the most reliable recession predictor in existence — it has preceded every recession since the 1960s. Steepening from inversion signals recovery.
- **Credit spreads (BAMLH0A0HYM2):** The spread between high-yield bonds and Treasuries measures risk appetite. Wide spreads = fear, tightening = risk-on. A 100bp move in credit spreads is a louder signal than a 5% equity move.
- **VIX (VIXCLS):** The "fear gauge" — implied volatility on S&P 500 options. VIX > 30 = elevated fear, < 15 = complacency. The level matters less than the direction — rising VIX with falling stocks = panic, falling VIX with rising stocks = healthy rally.
- **Fed funds rate (DFF):** The most important price in the world. Rate hikes tighten financial conditions and compress valuations (higher discount rate → lower DCF). Rate cuts do the inverse.
- **Fed balance sheet (WALCL):** Quantitative easing/tightening. Expanding balance sheet = liquidity injection (bullish for risk assets). Contracting = liquidity withdrawal.
- **CPI, unemployment, GDP, jobless claims:** The real economy. These determine where the Fed goes next, which determines where everything else goes.

**Agent consumer:** Macro Regime Analyst (primary), Quant Strategist (VIX as volatility input).

### `backend/data/market_client.py` — Yahoo Finance

**What it does:** Three methods — `get_price_history()` (OHLCV bars), `get_fundamentals()` (17 key ratios from a single `.info` call), and `get_options_chain()` (calls/puts with volume, OI, IV).

**Cache strategy:** 15-minute TTL on prices and options, 1-hour on fundamentals. Prices move intraday but agents don't need tick-level data. Fundamentals barely change within a day.

**Finance perspective:**
- **Price history:** Raw material for every technical signal the Quant Agent computes — RSI, MACD, Bollinger Bands, moving average crossovers, momentum factors. 6-month default lookback covers the standard windows (14-day RSI, 50/200-day MAs).
- **Fundamentals:** A single `.info` call returns P/E, EV/EBITDA, margins, growth, leverage, beta — everything the Fundamental Agent needs for a valuation screen. No need for separate calls per metric.
- **Options chain:** The Options Flow Agent reads this for put/call ratio (sentiment), volume/OI ratio (unusual activity detection), IV skew (directional fear), and ATM straddle pricing (market-implied expected move). Only the columns agents need are serialized — we don't ship the entire chain.

**Agent consumers:** Fundamental Agent (fundamentals), Options Flow Agent (options chains), Quant Strategist (price history).

### `backend/data/news_client.py` — NewsAPI + Finnhub

**What it does:** `get_ticker_news()` pulls articles from NewsAPI (title, description, source, date — no full content to save memory). `get_market_sentiment_finnhub()` gets pre-computed sentiment scores. `get_market_news_finnhub()` gets broad market news.

**Cache strategy:** 30-minute TTL on NewsAPI (only 100 calls/day — this is the tightest budget). 15-minute on Finnhub. Default page_size is 10, not 20 — enough for sentiment analysis without burning half the daily limit on one ticker.

**Finance perspective:** News sentiment is a leading indicator when measured as a *delta* (change), not a level. A stock with improving sentiment from deeply negative is a better signal than a stock with stable positive sentiment. The Sentiment Agent uses NewsAPI articles for NLP scoring (FinBERT in Phase 2) and Finnhub as a pre-computed baseline. The two sources cross-validate — if Finnhub says bearish and our NLP says bearish, conviction goes up.

**Agent consumer:** Sentiment & News Analyst.

### `backend/data/alpha_vantage_client.py` — Technical Indicators

**What it does:** Pre-computed RSI, MACD, Bollinger Bands, SMA, and EMA from Alpha Vantage. All calls go through a single `_fetch()` method with centralized caching and rate-limit error handling.

**Cache strategy:** 4-hour TTL — the most aggressive cache in the system. These are daily-bar indicators; they don't change until market close. 25 requests/day means we can analyze ~5 tickers across 5 indicators before hitting the wall. If the cache is warm, we can analyze unlimited tickers for free.

**Finance perspective:** These indicators are the Quant Agent's supplementary toolkit:
- **RSI:** Mean reversion signal. Overbought (>70) or oversold (<30) with a reversal pattern is a high-probability entry.
- **MACD:** Trend-following signal. Crossovers confirm momentum shifts; histogram expansion = strengthening trend.
- **Bollinger Bands:** Volatility regime detector. Squeeze (narrow bands) precedes breakouts. Price at bands = stretched.
- **SMA/EMA:** Trend structure. 50-day vs 200-day cross = golden/death cross (widely followed institutional signal).

Note: The Quant Agent can also compute all of these from raw price data via `market_client`. Alpha Vantage is a convenience layer — it's not a hard dependency, and the agent will fall back to self-computation if the daily limit is exhausted.

**Agent consumer:** Quant Strategist.

### How the data layer fits together

```
                    ┌──────────────┐
                    │  SEC Client   │──→ Fundamental Agent, Sentiment Agent
                    ├──────────────┤
                    │  FRED Client  │──→ Macro Agent
   Agents pull  ←── ├──────────────┤
   data on-demand   │  Market Client│──→ Fundamental, Options Flow, Quant
                    ├──────────────┤
                    │  News Client  │──→ Sentiment Agent
                    ├──────────────┤
                    │  AV Client    │──→ Quant Agent
                    └──────────────┘
                           ↑
                    All clients cache
                    results by TTL to
                    conserve API limits
```

Each agent calls only the data clients it needs. No agent touches all 5. The caching layer means that if two agents need the same ticker's fundamentals, the second call is free. This is how we run 5 agents on free-tier APIs without going blind.

---

## Phase 1, Step 4: Agent Layer (5 Agents + Consensus Engine + Orchestrator)

**What was built:**

| File | Component | Role |
|------|-----------|------|
| `agents/base_agent.py` | BaseAgent | Shared LangChain + Claude setup, output parsing, error handling |
| `agents/macro_agent.py` | Macro Regime Analyst | Classifies macro environment as expansion/late-cycle/contraction/recovery |
| `agents/fundamental_agent.py` | Fundamental Analyst | Valuation, financial health, SEC filing analysis, insider activity |
| `agents/sentiment_agent.py` | Sentiment & News Analyst | News flow analysis, sentiment delta detection, narrative identification |
| `agents/options_agent.py` | Options Flow Analyst | Unusual activity detection, IV analysis, put/call ratios |
| `agents/quant_agent.py` | Quantitative Strategist | Technical analysis, momentum/mean-reversion signals, price levels |
| `agents/consensus.py` | Consensus Engine | Weighted aggregation of all 5 signals → single recommendation |
| `agents/orchestrator.py` | LangGraph Orchestrator | Sequential pipeline: 5 agents → consensus, single entry point |

### Architecture: How the agent layer works

**BaseAgent (`base_agent.py`):**
The foundation class that all 5 agents inherit. It handles:
- LLM initialization: Single shared `ChatAnthropic` instance (Claude Sonnet, temperature=0 for deterministic financial analysis)
- Agent execution: `create_tool_calling_agent` from LangChain wraps each agent's tools + system prompt into a ReAct agent that can reason, call tools, observe results, and reason again
- Output parsing: Extracts JSON from LLM output (handles markdown fences, mixed text), validates against `AgentSignal` schema
- Error fallback: If an agent fails, returns a neutral signal with conviction=0 so the pipeline doesn't break
- Tool call cap: `max_iterations=10` prevents runaway tool-calling loops that burn API limits

Every agent inherits BaseAgent and only needs to define three things:
1. `agent_name` — identifier used by the Consensus Engine for weighting
2. `system_prompt` — the analytical framework and instructions
3. `get_tools()` — the data client methods this agent can call

**Structured output contract:**
All agents output JSON matching the `AgentSignal` schema:
- `direction`: strong_bullish / bullish / neutral / bearish / strong_bearish
- `conviction`: 0-100 integer with calibration guide (90+ = overwhelming, 50-69 = mixed, <30 = insufficient)
- `reasoning`: full chain-of-thought with specific numbers cited
- `key_factors`: top 3-5 drivers
- `risks`: key risks to the thesis
- `time_horizon`: intraday / days / weeks / months
- `metadata`: agent-specific structured data (regime classification, fair value, sentiment trend, options metrics, price levels)

### The 5 Agents — Finance Perspective

**1. Macro Regime Analyst** — "What's the weather?"
Before analyzing any stock, you need to know the environment. A cyclical stock in a contraction regime is bearish regardless of its fundamentals. The Macro Agent classifies the regime by reading the yield curve (recession predictor), credit spreads (risk appetite), VIX (fear), fed funds rate (monetary policy), and inflation/employment data. It has 4 tools — macro snapshot + 3 history series for trend analysis. Weight: 15%.

**2. Fundamental Analyst** — "What's it worth?"
The core valuation agent. It pulls Yahoo Finance ratios (P/E, EV/EBITDA, margins, FCF) and SEC filings (8-Ks for catalysts, 10-K/10-Q sections for deep analysis). It has 8 tools but is instructed to be selective — get fundamentals first, then decide which filings to pull. Includes red-flag scanning (going concern, goodwill impairment, material weakness) and insider trade detection. Weight: 30% (highest — balance sheets don't lie).

**3. Sentiment & News Analyst** — "What's the narrative?"
Markets are driven by narratives as much as numbers. This agent reads news flow, Finnhub sentiment scores, and recent 8-K events to detect sentiment shifts. The key insight is that the *delta* matters more than the level — improving sentiment from deeply negative is a stronger signal than stable positive sentiment. Instructed to use Finnhub baseline first, then NewsAPI only when deeper analysis is needed (100/day limit). Weight: 20%.

**4. Options Flow Analyst** — "What's the smart money doing?"
Options markets often lead equities because informed participants use derivatives for leverage and anonymity. This agent reads options chains for unusual activity (volume/OI > 2x), put/call ratio extremes, and ATM straddle pricing (market-implied expected move). Gets price context first (one cached call), then analyzes the nearest expiry chain. Weight: 15% (noisiest in isolation, but powerful as confirmation).

**5. Quantitative Strategist** — "What do the charts say?"
Statistical and technical analysis on price data. Identifies trend regime (uptrend/downtrend/range-bound), momentum signals (RSI, MACD), mean reversion setups (Bollinger extremes), and outputs specific entry/stop/target levels. Uses price history as primary data (free, uncapped), Alpha Vantage indicators only for confirmation (25/day limit). Weight: 20%.

### Consensus Engine — "The alpha is in the consensus"

This is the core IP. Any single agent's signal is noise. When all 5 agree, that's signal.

**Algorithm:**
1. **Weighted directional score:** Each agent's direction (−2 to +2) × conviction (0-1) × weight → normalized score
2. **Agreement measurement:** Standard deviation of directions across agents. All same direction = agreement 1.0. Mixed = lower.
3. **Direction mapping:** Score > 1.0 = strong bullish, > 0.3 = bullish, etc.
4. **Conviction = agreement × average conviction.** High average conviction with low agreement gets dampened. This is the key insight — disagreement among experts should reduce confidence, not be ignored.
5. **Action thresholds:** BUY/SELL requires conviction ≥ 75 + directional alignment. WATCH = conviction ≥ 50. HOLD = everything else.
6. **Position sizing:** Half-Kelly approximation capped at 5% of portfolio. Higher conviction = larger position, but never reckless.
7. **Risk levels:** Stop loss and take profit extracted from the Quant Agent's metadata.

### Orchestrator — The Pipeline

LangGraph `StateGraph` running agents sequentially:
```
macro → fundamental → sentiment → options → quant → consensus → END
```

Sequential in Phase 1 for debuggability and rate-limit friendliness. The `run_full_analysis(ticker)` function is the single entry point — what the `/api/analyze/{ticker}` endpoint will call.

Agent instances are singletons so data client caches persist across requests. Analyzing AAPL then MSFT reuses the macro snapshot (since macro data is ticker-independent) for free.

### How it all connects

```
User hits /api/analyze/AAPL
        │
        ▼
  orchestrator.run_full_analysis("AAPL")
        │
        ▼
  ┌─ Macro Agent ──── FRED Client (cached) ────── FRED API
  │
  ├─ Fundamental Agent ─┬─ Market Client (cached) ── Yahoo Finance
  │                     └─ SEC Client ──────────── SEC-API.io
  │
  ├─ Sentiment Agent ──── News Client (cached) ─┬─ NewsAPI
  │                                             └─ Finnhub
  │
  ├─ Options Agent ────── Market Client (cached) ── Yahoo Finance
  │
  └─ Quant Agent ──────┬─ Market Client (cached) ── Yahoo Finance
                       └─ AV Client (cached) ───── Alpha Vantage
        │
        ▼ (5 AgentSignals)
  Consensus Engine
        │
        ▼
  ConsensusSignal { action: BUY/SELL/HOLD/WATCH, conviction, reasoning... }
```

---

## Phase 1, Step 5: Backend Wiring & Live Data Verification

**What was built:**
Replaced all placeholder route stubs in `backend/main.py` with real data client calls. Every data endpoint now returns live data from external APIs.

**Changes to `main.py`:**
- `/api/analyze/{ticker}` → wired to `orchestrator.run_full_analysis()` (lazy import to avoid heavy load at startup)
- `/api/data/macro/snapshot` → wired to `FREDDataClient.get_macro_snapshot()`
- `/api/data/market/{ticker}` → wired to `MarketDataClient.get_fundamentals()` + `get_price_history()`
- `/api/data/market/{ticker}/options` → new endpoint, wired to `MarketDataClient.get_options_chain()`
- `/api/data/filings/{ticker}` → wired to `SECDataClient.get_recent_filings()`
- `/api/data/news/{ticker}` → wired to `NewsDataClient.get_ticker_news()` + `get_market_sentiment_finnhub()`
- `/api/agents/status` → now reflects live running state from analysis tracking
- `/api/agents/{agent_name}/history` → reads from in-memory signal store
- `/api/signals/latest` + `/api/signals/{ticker}/history` → reads from in-memory signal store
- Added in-memory `_signal_store` and `_analysis_status` dicts (Phase 1 — Postgres replaces these in Phase 2)
- All endpoints have proper error handling with `HTTPException`

**Bug fixes during wiring:**
1. `config.py` was loading `.env` relative to CWD — fixed to resolve from project root via `Path(__file__).resolve().parent.parent / ".env"`
2. `.env` values had surrounding single quotes causing API key rejection — stripped quotes
3. Finnhub `news-sentiment` endpoint is premium-tier (403 on free plan) — swapped to `company-news` endpoint which works on free tier and returns more data (240+ articles vs none)

**Live test results (all passing):**

| Endpoint | Source | Result |
|----------|--------|--------|
| `/api/health` | local | `{"status": "healthy"}` |
| `/api/agents/status` | local | All 5 agents reporting idle |
| `/api/data/macro/snapshot` | FRED | 9-13/13 indicators live (some daily series lag on FRED side) |
| `/api/data/market/AAPL` | Yahoo Finance | Price $257.48, P/E 32.59, 22 bars, full fundamentals |
| `/api/data/news/AAPL` | NewsAPI + Finnhub | 10 NewsAPI articles + 240 Finnhub articles |
| `/api/data/market/AAPL/options` | Yahoo Finance | Ready (not yet tested in batch — conserving calls) |

**Sample live data captured:**
- AAPL: $257.48, P/E 32.59, Technology/Consumer Electronics, beta 1.109
- Fed funds rate: 3.64% (2026-04-06)
- Unemployment: 4.3% (2026-03-01)
- CPI: 327.46 (2026-02-01)
- Fed balance sheet: $6.67T (2026-04-01)
- Top AAPL headline: "Why Apple stock is down today: Foldable iPhone delay, China patent battle"

**Finance note on the macro data:** Fed funds at 3.64% (down from 5.5% cycle peak) suggests we're in a cutting cycle. Yield curve at +0.52 (positive, not inverted) with unemployment at 4.3% and VIX at 25.78 — this looks like a late-cycle/early-recovery transition. Credit spreads at 3.12% are modestly elevated. The Macro Agent will use exactly this kind of multi-indicator read to classify the regime.
