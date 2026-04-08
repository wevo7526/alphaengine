# ALPHA ENGINE — Technical Specification

## Project: AI-Powered Quantitative Trading Intelligence Platform

**Codename:** Alpha Engine
**Author:** William Evans — Dominion Group
**Version:** 1.0 — Initial Architecture & Phase 1 Build
**Date:** April 2026
**Repository Target:** `alpha-engine/` (monorepo)
**Deployment:** Railway (backend + frontend)
**Portfolio Integration:** https://portfolio-production-e865.up.railway.app/

---

## 1. VISION & PRODUCT THESIS

Alpha Engine is an AI-powered quantitative trading intelligence platform that operates as a virtual trading desk. It deploys specialized AI agents — each acting as a domain expert (macro analyst, fundamental analyst, sentiment analyst, options flow analyst, quantitative strategist) — that independently analyze market data and then converge through a consensus mechanism to produce high-conviction trade ideas.

The human operator (the "Managing Director") receives synthesized intelligence with conviction scores, risk parameters, and full reasoning chains — then makes the final execution decision. This is not a black-box trading bot. It is an AI research team that produces institutional-grade analysis and trade recommendations.

**The alpha is in the consensus.** Any single signal is noise. When the macro regime, the fundamental picture, the sentiment shift, the options flow, and the quantitative model all agree — that's signal.

### Dual Revenue Path

1. **Direct Trading Revenue:** Trade personal/fund capital using the platform's intelligence. Target 30–50% annual returns. Scale AUM from personal capital → friends & family → institutional LP capital.
2. **Platform Licensing:** Productize the infrastructure for emerging managers ($5K–$25K/month). 500 funds × $10K/mo = $60M ARR = $1B+ valuation at vertical SaaS multiples.

---

## 2. SYSTEM ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────┐
│                      NEXT.JS FRONTEND                       │
│         (Dashboard, Agent Views, Trade Console, MD Desk)     │
│                    Deployed on Railway                       │
└────────────────────────────┬────────────────────────────────┘
                             │ REST + WebSocket
┌────────────────────────────┴────────────────────────────────┐
│                    FASTAPI BACKEND (Python)                  │
│                    Deployed on Railway                       │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Agent        │  │  Consensus   │  │  Execution   │       │
│  │  Orchestrator │──│  Engine      │──│  Layer       │       │
│  └──────┬───────┘  └──────────────┘  └──────────────┘       │
│         │                                                    │
│  ┌──────┴──────────────────────────────────────────┐        │
│  │              AGENT POOL (LangChain)              │        │
│  │                                                  │        │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐           │        │
│  │  │ Macro   │ │ Funda-  │ │ Senti-  │           │        │
│  │  │ Analyst │ │ mental  │ │ ment    │           │        │
│  │  │ Agent   │ │ Agent   │ │ Agent   │           │        │
│  │  └─────────┘ └─────────┘ └─────────┘           │        │
│  │  ┌─────────┐ ┌─────────┐                       │        │
│  │  │ Options │ │ Quant   │                       │        │
│  │  │ Flow    │ │ Strat   │                       │        │
│  │  │ Agent   │ │ Agent   │                       │        │
│  │  └─────────┘ └─────────┘                       │        │
│  └─────────────────────────────────────────────────┘        │
│                                                             │
│  ┌──────────────────────────────────────────────────┐       │
│  │              DATA INGESTION LAYER                 │       │
│  │                                                   │       │
│  │  SEC-API.io │ FRED │ News APIs │ Yahoo Finance   │       │
│  │  Alpha Vantage │ Polygon.io (future)             │       │
│  └──────────────────────────────────────────────────┘       │
│                                                             │
│  ┌──────────────────────────────────────────────────┐       │
│  │              STORAGE LAYER                        │       │
│  │  PostgreSQL (Railway) │ Redis (caching/queues)    │       │
│  └──────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. TECH STACK

### Backend (Python)

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Framework | FastAPI | Async REST + WebSocket endpoints |
| Agent Framework | LangChain + LangGraph | Agent orchestration, tool use, chains |
| LLM Provider | Anthropic Claude API (claude-sonnet-4-20250514) | Agent reasoning, NLP analysis |
| NLP | spaCy, transformers (HuggingFace), NLTK | Sentiment analysis, entity extraction, text processing |
| Quantitative | NumPy, Pandas, SciPy, scikit-learn | Statistical modeling, signal processing |
| Derivatives | QuantLib (optional), custom BSM module | Options pricing, Greeks, vol surface |
| Database | PostgreSQL (Railway managed) | Persistent storage for signals, trades, agent outputs |
| Cache/Queue | Redis (Railway managed) | Real-time data caching, task queues |
| Task Scheduler | APScheduler or Celery (with Redis) | Scheduled data ingestion, agent runs |
| Data Validation | Pydantic v2 | Request/response schemas, agent output validation |

### Frontend (Next.js / React)

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | Next.js 14+ (App Router) | SSR, routing, API routes for BFF |
| UI Library | React 18 + TypeScript | Component architecture |
| Styling | Tailwind CSS | Rapid UI development |
| Charts | Recharts + Lightweight Charts (TradingView) | Price charts, signal visualizations |
| State | Zustand or React Query | Client state + server state management |
| Real-time | Socket.io client | Live agent updates, price feeds |
| Tables | TanStack Table | Trade blotter, agent output tables |

### Infrastructure

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Hosting | Railway | Backend + frontend + DB + Redis |
| CI/CD | Railway auto-deploy from GitHub | Push-to-deploy |
| Environment | Railway env vars | API keys, secrets |
| Monitoring | Railway metrics + custom logging | System health |

---

## 4. DATA SOURCES & INGESTION

### Phase 1 Data Sources (Build Now)

#### 4.1 SEC EDGAR — via sec-api.io

**API Key:** Store as `SEC_API_KEY` in Railway env vars.

**Endpoints to integrate:**

| Endpoint | Use Case | Agent Consumer |
|----------|----------|----------------|
| Query API (`/filings`) | Search 10-K, 10-Q, 8-K by ticker, date, form type | Fundamental Agent |
| Full-Text Search API | Search filing content for keywords (e.g., "goodwill impairment", "going concern") | Fundamental Agent, Sentiment Agent |
| 10-K/10-Q Extractor | Pull specific sections: MD&A, Risk Factors, Financial Statements | Fundamental Agent |
| 8-K Extractor | Material events: earnings, M&A, executive changes, guidance revisions | Sentiment Agent |
| Insider Trading API (Forms 3/4/5) | Insider buys/sells, cluster detection | Fundamental Agent |
| 13F API | Institutional holdings changes (Bridgewater, Berkshire, etc.) | Fundamental Agent |
| Real-Time Stream (WebSocket) | Live filing alerts — new 8-Ks, insider trades within 300ms of EDGAR publish | All Agents (event trigger) |

**Implementation pattern:**

```python
# backend/data/sec_client.py
from sec_api import QueryApi, FullTextSearchApi, ExtractorApi
import os

class SECDataClient:
    def __init__(self):
        self.api_key = os.environ["SEC_API_KEY"]
        self.query_api = QueryApi(api_key=self.api_key)
        self.fulltext_api = FullTextSearchApi(api_key=self.api_key)
        self.extractor_api = ExtractorApi(api_key=self.api_key)

    def get_recent_filings(self, ticker: str, form_type: str = "8-K", limit: int = 10):
        query = {
            "query": {
                "query_string": {
                    "query": f'ticker:"{ticker}" AND formType:"{form_type}"'
                }
            },
            "from": "0",
            "size": str(limit),
            "sort": [{"filedAt": {"order": "desc"}}]
        }
        return self.query_api.get_filings(query)

    def extract_mda(self, filing_url: str) -> str:
        """Extract Management Discussion & Analysis from 10-K/10-Q"""
        return self.extractor_api.get_section(filing_url, "7", "text")

    def extract_risk_factors(self, filing_url: str) -> str:
        """Extract Risk Factors section"""
        return self.extractor_api.get_section(filing_url, "1A", "text")

    def search_filings_fulltext(self, query: str, form_types: list = None):
        """Full-text search across all filings"""
        search_query = {
            "query": query,
            "formTypes": form_types or ["10-K", "10-Q", "8-K"],
            "startDate": "2024-01-01",
            "endDate": "2026-12-31"
        }
        return self.fulltext_api.get_filings(search_query)
```

#### 4.2 FRED (Federal Reserve Economic Data)

**API:** Free via `fredapi` Python package. Get API key from https://fred.stlouisfed.org/docs/api/api_key.html
**Store as:** `FRED_API_KEY`

**Key Series to Ingest:**

| Series ID | Name | Agent Consumer | Frequency |
|-----------|------|----------------|-----------|
| DFF | Fed Funds Effective Rate | Macro Agent | Daily |
| T10Y2Y | 10Y-2Y Treasury Spread (yield curve) | Macro Agent | Daily |
| T10YIE | 10Y Breakeven Inflation | Macro Agent | Daily |
| BAMLH0A0HYM2 | High Yield OAS (credit spreads) | Macro Agent | Daily |
| VIXCLS | CBOE VIX | Macro Agent, Quant Agent | Daily |
| UNRATE | Unemployment Rate | Macro Agent | Monthly |
| CPIAUCSL | CPI (inflation) | Macro Agent | Monthly |
| GDP | Real GDP | Macro Agent | Quarterly |
| WALCL | Fed Balance Sheet | Macro Agent | Weekly |
| DCOILWTICO | WTI Crude Oil | Macro Agent | Daily |
| DTWEXBGS | Trade-Weighted USD Index | Macro Agent | Daily |
| M2SL | M2 Money Supply | Macro Agent | Monthly |
| ICSA | Initial Jobless Claims | Macro Agent | Weekly |

```python
# backend/data/fred_client.py
from fredapi import Fred
import pandas as pd
import os

class FREDDataClient:
    MACRO_SERIES = {
        "DFF": "fed_funds_rate",
        "T10Y2Y": "yield_curve_spread",
        "T10YIE": "breakeven_inflation",
        "BAMLH0A0HYM2": "credit_spreads",
        "VIXCLS": "vix",
        "UNRATE": "unemployment",
        "CPIAUCSL": "cpi",
        "WALCL": "fed_balance_sheet",
        "ICSA": "jobless_claims",
    }

    def __init__(self):
        self.fred = Fred(api_key=os.environ["FRED_API_KEY"])

    def get_macro_snapshot(self) -> dict:
        """Pull latest values for all macro indicators"""
        snapshot = {}
        for series_id, name in self.MACRO_SERIES.items():
            series = self.fred.get_series(series_id)
            snapshot[name] = {
                "value": float(series.iloc[-1]),
                "previous": float(series.iloc[-2]),
                "change": float(series.iloc[-1] - series.iloc[-2]),
                "date": str(series.index[-1].date()),
            }
        return snapshot

    def get_series_history(self, series_id: str, lookback_days: int = 252) -> pd.DataFrame:
        """Pull historical data for a series"""
        return self.fred.get_series(series_id).tail(lookback_days).to_frame(name="value")
```

#### 4.3 News & Sentiment Data

**Primary: NewsAPI.org** (free tier: 100 requests/day, 1-month archive)
**Store as:** `NEWS_API_KEY`

**Supplementary: Finnhub** (free tier: 60 calls/min, real-time news + sentiment)
**Store as:** `FINNHUB_API_KEY`

```python
# backend/data/news_client.py
import requests
import os

class NewsDataClient:
    def __init__(self):
        self.newsapi_key = os.environ["NEWS_API_KEY"]
        self.finnhub_key = os.environ.get("FINNHUB_API_KEY")

    def get_ticker_news(self, ticker: str, days_back: int = 7) -> list:
        """Fetch recent news articles for a ticker"""
        # Company name lookup would happen upstream
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": ticker,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": 20,
            "apiKey": self.newsapi_key,
        }
        resp = requests.get(url, params=params)
        return resp.json().get("articles", [])

    def get_market_sentiment_finnhub(self, ticker: str) -> dict:
        """Get pre-computed sentiment from Finnhub"""
        if not self.finnhub_key:
            return {}
        url = f"https://finnhub.io/api/v1/news-sentiment"
        params = {"symbol": ticker, "token": self.finnhub_key}
        resp = requests.get(url, params=params)
        return resp.json()
```

#### 4.4 Market Data — Yahoo Finance (via yfinance)

**No API key required.** Free, reliable for daily OHLCV, fundamentals, options chains.

```python
# backend/data/market_client.py
import yfinance as yf
import pandas as pd

class MarketDataClient:
    def get_price_history(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        stock = yf.Ticker(ticker)
        return stock.history(period=period)

    def get_fundamentals(self, ticker: str) -> dict:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "market_cap": info.get("marketCap"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margin": info.get("profitMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "free_cash_flow": info.get("freeCashflow"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "short_ratio": info.get("shortRatio"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }

    def get_options_chain(self, ticker: str, expiry: str = None) -> dict:
        stock = yf.Ticker(ticker)
        expirations = stock.options
        if not expirations:
            return {"expirations": [], "calls": [], "puts": []}
        target = expiry or expirations[0]
        chain = stock.option_chain(target)
        return {
            "expiration": target,
            "all_expirations": list(expirations),
            "calls": chain.calls.to_dict(orient="records"),
            "puts": chain.puts.to_dict(orient="records"),
        }
```

#### 4.5 Alpha Vantage (Supplementary — Technical Indicators)

**Store as:** `ALPHA_VANTAGE_KEY` (free tier: 25 requests/day)

Used for pre-computed technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands) to supplement the Quant Agent.

---

## 5. AI AGENT ARCHITECTURE

### 5.1 Agent Design Philosophy

Each agent is a LangChain agent with:
- A **system prompt** defining its role, expertise, and analytical framework
- **Tools** (data source connectors) it can call
- A **structured output schema** (Pydantic) so its analysis is machine-readable
- A **conviction score** (0–100) for its conclusion
- A **reasoning chain** (full explanation of how it arrived at its conclusion)

All agents share a common output interface so the Consensus Engine can aggregate them.

### 5.2 Common Agent Output Schema

```python
# backend/agents/schemas.py
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime

class SignalDirection(str, Enum):
    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"

class AgentSignal(BaseModel):
    """Standardized output from every agent"""
    agent_name: str
    ticker: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    direction: SignalDirection
    conviction: int = Field(ge=0, le=100, description="0-100 conviction score")
    reasoning: str = Field(description="Full reasoning chain explaining the signal")
    key_factors: list[str] = Field(description="Top 3-5 factors driving the signal")
    risks: list[str] = Field(description="Key risks to the thesis")
    time_horizon: str = Field(description="Expected holding period: intraday/days/weeks/months")
    data_freshness: datetime = Field(description="Timestamp of most recent data used")
    metadata: dict = Field(default_factory=dict, description="Agent-specific additional data")

class ConsensusSignal(BaseModel):
    """Output from the Consensus Engine after aggregating all agents"""
    ticker: str
    timestamp: datetime
    overall_direction: SignalDirection
    overall_conviction: int = Field(ge=0, le=100)
    agent_signals: list[AgentSignal]
    consensus_reasoning: str
    agreement_score: float = Field(ge=0, le=1, description="How much agents agree (1 = unanimous)")
    recommended_action: str  # "BUY", "SELL", "HOLD", "WATCH"
    position_size_suggestion: float = Field(description="Suggested position size as % of portfolio")
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_reward_ratio: Optional[float] = None
```

### 5.3 Agent Definitions

#### Agent 1: Macro Regime Analyst

**Role:** Determine the current macroeconomic regime and whether it favors risk-on or risk-off positioning.

**Data Sources:** FRED API (yield curve, credit spreads, VIX, fed funds, inflation, employment, GDP, M2, Fed balance sheet)

**System Prompt Core:**

```
You are a senior macroeconomic strategist at a quantitative hedge fund. Your job is
to classify the current macro regime and determine whether conditions favor
risk-on (equities, credit, growth) or risk-off (treasuries, cash, defensives)
positioning.

You analyze: yield curve shape and dynamics, credit spread levels and trends,
volatility regime (VIX level and term structure), monetary policy stance
(fed funds rate, balance sheet trajectory), inflation dynamics (CPI, breakeven
inflation), labor market conditions, and GDP trajectory.

You classify the regime as one of:
- EXPANSION: Growth accelerating, inflation moderate, spreads tight, curve steepening
- LATE_CYCLE: Growth peaking, inflation rising, spreads widening, curve flattening
- CONTRACTION: Growth declining, spreads blowing out, curve inverting
- RECOVERY: Growth bottoming, spreads tightening from wides, curve steepening

For any given ticker, assess whether the current macro regime supports or
undermines the investment thesis. A cyclical stock in a CONTRACTION regime gets
a bearish macro overlay regardless of its fundamentals.

Always provide your conviction score (0-100) and full reasoning chain.
```

**Tools:** `get_macro_snapshot()`, `get_series_history()`, `get_yield_curve_analysis()`

---

#### Agent 2: Fundamental Analyst

**Role:** Analyze company fundamentals, financial health, valuation, and recent SEC filings for material changes.

**Data Sources:** SEC-API.io (10-K, 10-Q, 8-K, insider trading, 13F), Yahoo Finance (fundamentals)

**System Prompt Core:**

```
You are a senior equity research analyst at a fundamental hedge fund. You
analyze companies through their financial statements, SEC filings, and
valuation metrics to determine intrinsic value and identify catalysts.

Your framework:
1. FINANCIAL HEALTH: Revenue growth trajectory, margin trends, cash flow
   generation, balance sheet strength (debt/equity, interest coverage,
   current ratio)
2. VALUATION: P/E vs sector median, EV/EBITDA vs historical range, PEG ratio,
   FCF yield, price-to-book vs ROE
3. CATALYSTS: Recent 8-K filings (earnings surprises, M&A, executive changes,
   guidance revisions), insider buying/selling clusters, institutional
   accumulation (13F changes)
4. QUALITY: Earnings quality (accruals ratio), revenue sustainability,
   competitive moat indicators

When analyzing SEC filings, pay special attention to:
- MD&A language changes between quarters (hedging words, tone shifts)
- Risk factor additions or removals
- Going concern language
- Goodwill impairment indicators
- Related party transactions
- Off-balance-sheet arrangements

Output a fair value estimate with a margin of safety calculation.
```

**Tools:** `get_fundamentals()`, `get_recent_filings()`, `extract_mda()`, `extract_risk_factors()`, `get_insider_trades()`, `get_13f_holdings()`

---

#### Agent 3: Sentiment & News Analyst

**Role:** Analyze news sentiment, earnings call tone, and public narrative to detect sentiment shifts before they're priced in.

**Data Sources:** NewsAPI, Finnhub sentiment, SEC 8-K filings (earnings transcripts)

**System Prompt Core:**

```
You are a sentiment analysis specialist at a quantitative fund. You analyze
news flow, earnings call transcripts, and public narratives to detect
sentiment shifts that precede price movements.

Your framework:
1. NEWS FLOW ANALYSIS: Volume of coverage (increasing/decreasing), tone
   distribution (positive/negative/neutral), source quality weighting
   (Reuters/Bloomberg > aggregators > social media)
2. EARNINGS TRANSCRIPT ANALYSIS: Management tone vs prior quarters, use of
   hedging language ("challenging environment", "headwinds"), forward guidance
   language confidence level, Q&A tone vs prepared remarks tone
3. NARRATIVE DETECTION: Identify emerging narratives (turnaround story,
   growth acceleration, margin expansion, competitive threat) and assess
   whether the narrative is early (alpha opportunity) or consensus (priced in)
4. SENTIMENT DELTA: The absolute sentiment matters less than the CHANGE in
   sentiment. A stock with improving sentiment from very negative is more
   interesting than a stock with stable positive sentiment.

Use NLP techniques:
- VADER or FinBERT for financial sentiment scoring
- Named entity recognition for company/executive extraction
- Keyword frequency analysis for theme detection
- Temporal sentiment tracking (sentiment trajectory over days/weeks)

Focus on the DELTA, not the level. What changed? What's new? What shifted?
```

**Tools:** `get_ticker_news()`, `get_market_sentiment_finnhub()`, `analyze_transcript_sentiment()`, `get_8k_text()`

**NLP Pipeline:**

```python
# backend/agents/nlp/sentiment.py
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
import spacy

class FinancialSentimentAnalyzer:
    def __init__(self):
        # FinBERT for financial-domain sentiment
        self.finbert = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert"
        )
        # spaCy for entity extraction
        self.nlp = spacy.load("en_core_web_sm")

    def analyze_article(self, text: str) -> dict:
        # Chunk text for FinBERT (max 512 tokens)
        chunks = self._chunk_text(text, max_length=400)
        sentiments = [self.finbert(chunk)[0] for chunk in chunks]

        # Aggregate sentiment across chunks
        scores = {"positive": 0, "negative": 0, "neutral": 0}
        for s in sentiments:
            scores[s["label"]] += s["score"]

        total = sum(scores.values())
        normalized = {k: v / total for k, v in scores.items()}

        # Extract entities
        doc = self.nlp(text)
        entities = [(ent.text, ent.label_) for ent in doc.ents
                    if ent.label_ in ("ORG", "PERSON", "MONEY", "PERCENT")]

        return {
            "sentiment_scores": normalized,
            "dominant_sentiment": max(normalized, key=normalized.get),
            "entities": entities,
            "confidence": max(normalized.values()),
        }

    def analyze_transcript_delta(self, current: str, previous: str) -> dict:
        """Compare sentiment between current and prior quarter transcript"""
        current_sentiment = self.analyze_article(current)
        previous_sentiment = self.analyze_article(previous)

        delta = {
            k: current_sentiment["sentiment_scores"][k] - previous_sentiment["sentiment_scores"][k]
            for k in current_sentiment["sentiment_scores"]
        }

        return {
            "current": current_sentiment,
            "previous": previous_sentiment,
            "delta": delta,
            "sentiment_improving": delta["positive"] > 0 and delta["negative"] < 0,
        }

    def _chunk_text(self, text: str, max_length: int = 400) -> list:
        words = text.split()
        chunks = []
        for i in range(0, len(words), max_length):
            chunks.append(" ".join(words[i:i + max_length]))
        return chunks
```

---

#### Agent 4: Options Flow Analyst

**Role:** Analyze options market data for unusual activity, positioning signals, and implied volatility dynamics.

**Data Sources:** Yahoo Finance options chains, calculated Greeks

**System Prompt Core:**

```
You are a derivatives specialist at a volatility-focused hedge fund. You
analyze options market data to extract positioning signals and detect unusual
activity that often precedes directional moves.

Your framework:
1. IMPLIED VOLATILITY ANALYSIS: Current IV vs 30-day average (IV rank),
   IV skew (put vs call IV), term structure (near-term vs far-term IV),
   IV crush/expansion around events
2. UNUSUAL OPTIONS ACTIVITY: High volume relative to open interest
   (volume/OI > 2x), large premium trades, sweeps vs blocks,
   put/call ratio extremes
3. GREEK ANALYSIS: Aggregate delta exposure (net directional bias),
   gamma exposure at key strikes (pin risk), vanna and charm flows
   (vol-price dynamics)
4. OPTIONS-IMPLIED PROBABILITIES: Extract market-implied move sizes
   from straddle pricing, compare to historical realized moves

Key signals:
- Smart money tends to buy calls/puts on sweeps (aggressive, lifting offers)
- Unusual put buying ahead of earnings = hedging or informed selling
- IV term structure inversion = market pricing near-term event risk
- Skew steepening = growing demand for downside protection

Always contextualize options signals with the underlying's price action
and fundamental picture. Options flow in isolation is noisy.
```

**Tools:** `get_options_chain()`, `calculate_greeks()`, `get_iv_history()`

**Custom Quantitative Module:**

```python
# backend/agents/quant/options_analytics.py
import numpy as np
from scipy.stats import norm

class OptionsAnalytics:
    @staticmethod
    def black_scholes(S, K, T, r, sigma, option_type="call"):
        """BSM pricing model"""
        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        if option_type == "call":
            return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:
            return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    @staticmethod
    def calculate_greeks(S, K, T, r, sigma, option_type="call"):
        d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        delta = norm.cdf(d1) if option_type == "call" else norm.cdf(d1) - 1
        gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
        theta = (-(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
                 - r * K * np.exp(-r * T) * norm.cdf(d2 if option_type == "call" else -d2))
        vega = S * norm.pdf(d1) * np.sqrt(T) / 100
        return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}

    @staticmethod
    def implied_move(straddle_price, stock_price):
        """Calculate market-implied expected move from ATM straddle"""
        return straddle_price / stock_price

    @staticmethod
    def put_call_ratio(calls_volume, puts_volume):
        if calls_volume == 0:
            return float('inf')
        return puts_volume / calls_volume

    @staticmethod
    def unusual_activity_score(volume, open_interest):
        """Score unusual options activity. > 2.0 is notable, > 5.0 is very unusual"""
        if open_interest == 0:
            return 0
        return volume / open_interest
```

---

#### Agent 5: Quantitative Strategist

**Role:** Apply statistical and technical analysis to price data to identify mean reversion, momentum, and breakout signals.

**Data Sources:** Yahoo Finance (price history), Alpha Vantage (technical indicators)

**System Prompt Core:**

```
You are a quantitative portfolio strategist who combines statistical analysis
with technical indicators to identify high-probability setups.

Your framework:
1. REGIME CLASSIFICATION: Is the stock trending (momentum) or mean-reverting?
   Use Hurst exponent, ADX, and autocorrelation to classify.
2. MOMENTUM SIGNALS: 12-1 month momentum factor, RSI divergences,
   MACD crossovers, moving average structure (golden/death cross)
3. MEAN REVERSION SIGNALS: Bollinger Band extremes, z-score of
   price vs 50-day SMA, RSI oversold/overbought with reversal candles
4. VOLATILITY ANALYSIS: Historical vs implied vol spread, Bollinger
   Band width (volatility squeeze → expansion), ATR regime
5. STATISTICAL EDGE: Backtest any signal pattern against historical
   data before including in conviction score. No signal without
   statistical backing.

Position sizing framework:
- Kelly Criterion for optimal sizing: f* = (bp - q) / b
- Adjust Kelly by 50% for real-world application (half-Kelly)
- Maximum position = 5% of portfolio for single names
- Correlate position sizes to conviction scores

Output specific entry, stop-loss, and take-profit levels with
risk/reward ratios. No trade idea without defined risk.
```

**Tools:** `get_price_history()`, `calculate_technical_indicators()`, `run_backtest()`

---

### 5.4 Consensus Engine

The Consensus Engine aggregates all agent signals and produces the final recommendation. This is the core IP.

```python
# backend/agents/consensus.py
from agents.schemas import AgentSignal, ConsensusSignal, SignalDirection
import numpy as np

class ConsensusEngine:
    # Weight each agent's signal (tunable hyperparameters)
    AGENT_WEIGHTS = {
        "macro_analyst": 0.15,
        "fundamental_analyst": 0.30,
        "sentiment_analyst": 0.20,
        "options_flow_analyst": 0.15,
        "quant_strategist": 0.20,
    }

    DIRECTION_SCORES = {
        SignalDirection.STRONG_BULLISH: 2,
        SignalDirection.BULLISH: 1,
        SignalDirection.NEUTRAL: 0,
        SignalDirection.BEARISH: -1,
        SignalDirection.STRONG_BEARISH: -2,
    }

    def evaluate(self, signals: list[AgentSignal]) -> ConsensusSignal:
        # Weighted directional score
        weighted_score = 0
        total_weight = 0
        for signal in signals:
            weight = self.AGENT_WEIGHTS.get(signal.agent_name, 0.1)
            direction_score = self.DIRECTION_SCORES[signal.direction]
            conviction_multiplier = signal.conviction / 100
            weighted_score += weight * direction_score * conviction_multiplier
            total_weight += weight

        normalized_score = weighted_score / total_weight if total_weight > 0 else 0

        # Calculate agreement score (how aligned are the agents?)
        directions = [self.DIRECTION_SCORES[s.direction] for s in signals]
        if len(set(directions)) == 1:
            agreement = 1.0
        else:
            # Normalized standard deviation (lower std = higher agreement)
            std = np.std(directions)
            agreement = max(0, 1 - std / 2)

        # Map normalized score to direction
        if normalized_score > 1.0:
            direction = SignalDirection.STRONG_BULLISH
        elif normalized_score > 0.3:
            direction = SignalDirection.BULLISH
        elif normalized_score > -0.3:
            direction = SignalDirection.NEUTRAL
        elif normalized_score > -1.0:
            direction = SignalDirection.BEARISH
        else:
            direction = SignalDirection.STRONG_BEARISH

        # Conviction = agreement × average conviction
        avg_conviction = np.mean([s.conviction for s in signals])
        overall_conviction = int(agreement * avg_conviction)

        # Action recommendation
        if overall_conviction >= 75 and direction in [SignalDirection.STRONG_BULLISH, SignalDirection.BULLISH]:
            action = "BUY"
        elif overall_conviction >= 75 and direction in [SignalDirection.STRONG_BEARISH, SignalDirection.BEARISH]:
            action = "SELL"
        elif overall_conviction >= 50:
            action = "WATCH"
        else:
            action = "HOLD"

        # Position sizing (half-Kelly approximation)
        if action in ["BUY", "SELL"]:
            # Simplified: higher conviction = larger position, capped at 5%
            position_pct = min(5.0, (overall_conviction / 100) * 7.0)
        else:
            position_pct = 0.0

        return ConsensusSignal(
            ticker=signals[0].ticker,
            timestamp=max(s.timestamp for s in signals),
            overall_direction=direction,
            overall_conviction=overall_conviction,
            agent_signals=signals,
            consensus_reasoning=self._build_consensus_narrative(signals, direction, agreement),
            agreement_score=agreement,
            recommended_action=action,
            position_size_suggestion=round(position_pct, 2),
        )

    def _build_consensus_narrative(self, signals, direction, agreement) -> str:
        """Use Claude to synthesize agent reasoning into a coherent narrative"""
        # This calls the LLM to produce a human-readable consensus memo
        # Implementation: format all agent signals into a prompt, ask Claude to synthesize
        summaries = []
        for s in signals:
            summaries.append(f"[{s.agent_name}] {s.direction.value} (conviction: {s.conviction}): {s.reasoning[:200]}")
        return f"Agreement: {agreement:.0%}. " + " | ".join(summaries)
```

---

## 6. AGENT ORCHESTRATION (LANGGRAPH)

Use LangGraph to orchestrate the multi-agent workflow:

```python
# backend/agents/orchestrator.py
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AnalysisState(TypedDict):
    ticker: str
    macro_signal: dict | None
    fundamental_signal: dict | None
    sentiment_signal: dict | None
    options_signal: dict | None
    quant_signal: dict | None
    consensus: dict | None

def build_analysis_graph():
    graph = StateGraph(AnalysisState)

    # Add agent nodes (each runs independently)
    graph.add_node("macro_agent", run_macro_agent)
    graph.add_node("fundamental_agent", run_fundamental_agent)
    graph.add_node("sentiment_agent", run_sentiment_agent)
    graph.add_node("options_agent", run_options_agent)
    graph.add_node("quant_agent", run_quant_agent)
    graph.add_node("consensus", run_consensus)

    # All agents run in parallel from START
    graph.set_entry_point("macro_agent")

    # Fan-out: all agents can run concurrently
    # In practice, use asyncio.gather() to parallelize
    graph.add_edge("macro_agent", "fundamental_agent")
    graph.add_edge("fundamental_agent", "sentiment_agent")
    graph.add_edge("sentiment_agent", "options_agent")
    graph.add_edge("options_agent", "quant_agent")

    # All agents feed into consensus
    graph.add_edge("quant_agent", "consensus")
    graph.add_edge("consensus", END)

    return graph.compile()
```

**NOTE FOR CLAUDE CODE:** In Phase 1, run agents sequentially. In Phase 2, refactor to use `asyncio.gather()` for true parallel execution. The sequential approach is simpler to debug and test.

---

## 7. BACKEND API ROUTES

```python
# backend/main.py — FastAPI application

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Alpha Engine API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === ANALYSIS ENDPOINTS ===

@app.post("/api/analyze/{ticker}")
async def analyze_ticker(ticker: str):
    """Run full agent analysis pipeline on a ticker. Returns consensus signal."""
    pass

@app.get("/api/analyze/{ticker}/status")
async def analysis_status(ticker: str):
    """Check status of an in-progress analysis (which agents have reported)."""
    pass

@app.get("/api/signals/latest")
async def latest_signals(limit: int = 20):
    """Get most recent consensus signals across all analyzed tickers."""
    pass

@app.get("/api/signals/{ticker}/history")
async def signal_history(ticker: str, days: int = 30):
    """Historical signals for a ticker to track agent accuracy over time."""
    pass

# === DATA ENDPOINTS ===

@app.get("/api/data/macro/snapshot")
async def macro_snapshot():
    """Current macro regime data from FRED."""
    pass

@app.get("/api/data/market/{ticker}")
async def market_data(ticker: str):
    """Price history, fundamentals, options chain for a ticker."""
    pass

@app.get("/api/data/filings/{ticker}")
async def sec_filings(ticker: str, form_type: str = "8-K", limit: int = 10):
    """Recent SEC filings for a ticker via sec-api.io."""
    pass

@app.get("/api/data/news/{ticker}")
async def news_feed(ticker: str):
    """Recent news with sentiment scores."""
    pass

# === AGENT ENDPOINTS ===

@app.get("/api/agents/status")
async def agent_status():
    """Health check for all agents."""
    pass

@app.get("/api/agents/{agent_name}/history")
async def agent_history(agent_name: str, limit: int = 50):
    """Historical signals from a specific agent for accuracy tracking."""
    pass

# === PORTFOLIO ENDPOINTS ===

@app.get("/api/portfolio/positions")
async def portfolio_positions():
    """Current portfolio positions and P&L."""
    pass

@app.get("/api/portfolio/risk")
async def portfolio_risk():
    """Portfolio-level risk metrics (beta, VaR, sector exposure)."""
    pass

# === WEBSOCKET ===

@app.websocket("/ws/analysis/{ticker}")
async def analysis_stream(websocket: WebSocket, ticker: str):
    """Stream real-time agent updates as they complete analysis."""
    await websocket.accept()
    # Stream each agent's signal as it completes
    # { "agent": "macro_analyst", "status": "complete", "signal": {...} }
    pass

@app.websocket("/ws/filings")
async def filing_stream(websocket: WebSocket):
    """Stream real-time SEC filing alerts (via sec-api.io WebSocket)."""
    await websocket.accept()
    pass
```

---

## 8. FRONTEND PAGES & COMPONENTS

### Page Structure (Next.js App Router)

```
app/
├── page.tsx                    # Dashboard — portfolio summary, latest signals, macro snapshot
├── analyze/
│   └── [ticker]/
│       └── page.tsx            # Deep analysis view — run agents, see consensus
├── agents/
│   └── page.tsx                # Agent performance — accuracy tracking, signal history
├── portfolio/
│   └── page.tsx                # Portfolio view — positions, P&L, risk metrics
├── filings/
│   └── page.tsx                # SEC filings monitor — real-time 8-K/insider alerts
├── news/
│   └── page.tsx                # News sentiment feed — scored, filterable
├── macro/
│   └── page.tsx                # Macro dashboard — FRED data, regime classification
└── settings/
    └── page.tsx                # API keys, agent weights, risk parameters
```

### Key UI Components

#### Dashboard (`/`)
- Portfolio summary card (total value, daily P&L, Sharpe ratio)
- Active signals ticker strip (latest consensus signals scrolling)
- Macro regime indicator (expansion/late-cycle/contraction/recovery with color)
- Top 5 latest agent consensus outputs with conviction bars
- Real-time filing alerts feed

#### Analysis View (`/analyze/[ticker]`)
- Ticker input with autocomplete
- "Run Analysis" button → triggers all 5 agents
- Real-time progress: show each agent card going from "Analyzing..." → complete with signal
- Agent cards arranged in a row: Macro | Fundamental | Sentiment | Options | Quant
- Each card shows: direction arrow, conviction bar (0-100), key factors, top risk
- Consensus panel at bottom: overall direction, conviction, recommended action, position size
- Full reasoning chain expandable for each agent
- Price chart (TradingView Lightweight Charts) with signal overlay points

#### MD Trade Console (`/analyze/[ticker]` — bottom panel)
- The "Managing Director Desk"
- Shows consensus recommendation prominently
- Entry price, stop loss, take profit fields (pre-populated by Quant Agent)
- Position size calculator (based on portfolio size and conviction)
- Risk/reward ratio visualization
- "Execute Trade" button (Phase 2 — connects to broker API)
- Trade journal: log the decision and reasoning for post-mortem analysis

---

## 9. DATABASE SCHEMA

```sql
-- Signals from individual agents
CREATE TABLE agent_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name VARCHAR(50) NOT NULL,
    ticker VARCHAR(10) NOT NULL,
    direction VARCHAR(20) NOT NULL,
    conviction INTEGER CHECK (conviction BETWEEN 0 AND 100),
    reasoning TEXT NOT NULL,
    key_factors JSONB,
    risks JSONB,
    time_horizon VARCHAR(20),
    data_freshness TIMESTAMP,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Consensus outputs
CREATE TABLE consensus_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    overall_direction VARCHAR(20) NOT NULL,
    overall_conviction INTEGER,
    agreement_score FLOAT,
    recommended_action VARCHAR(10),
    position_size_suggestion FLOAT,
    stop_loss FLOAT,
    take_profit FLOAT,
    risk_reward_ratio FLOAT,
    consensus_reasoning TEXT,
    agent_signal_ids UUID[],
    created_at TIMESTAMP DEFAULT NOW()
);

-- Trade journal (MD decisions)
CREATE TABLE trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    action VARCHAR(10) NOT NULL,  -- BUY, SELL, SHORT, COVER
    entry_price FLOAT,
    quantity FLOAT,
    stop_loss FLOAT,
    take_profit FLOAT,
    consensus_signal_id UUID REFERENCES consensus_signals(id),
    md_notes TEXT,
    status VARCHAR(20) DEFAULT 'open',  -- open, closed, stopped_out
    exit_price FLOAT,
    realized_pnl FLOAT,
    opened_at TIMESTAMP DEFAULT NOW(),
    closed_at TIMESTAMP
);

-- Portfolio state
CREATE TABLE portfolio (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker VARCHAR(10) NOT NULL,
    quantity FLOAT NOT NULL,
    avg_entry_price FLOAT NOT NULL,
    current_price FLOAT,
    unrealized_pnl FLOAT,
    weight FLOAT,  -- % of portfolio
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Macro regime snapshots
CREATE TABLE macro_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    regime VARCHAR(20) NOT NULL,
    indicators JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Agent accuracy tracking
CREATE TABLE agent_accuracy (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name VARCHAR(50) NOT NULL,
    signal_id UUID REFERENCES agent_signals(id),
    predicted_direction VARCHAR(20),
    actual_direction VARCHAR(20),
    predicted_conviction INTEGER,
    return_1d FLOAT,
    return_5d FLOAT,
    return_20d FLOAT,
    was_correct BOOLEAN,
    evaluated_at TIMESTAMP DEFAULT NOW()
);
```

---

## 10. PROJECT STRUCTURE

```
alpha-engine/
├── backend/
│   ├── main.py                         # FastAPI entry point
│   ├── config.py                       # Environment variables, settings
│   ├── requirements.txt
│   ├── data/
│   │   ├── __init__.py
│   │   ├── sec_client.py               # SEC-API.io integration
│   │   ├── fred_client.py              # FRED macro data
│   │   ├── market_client.py            # Yahoo Finance wrapper
│   │   ├── news_client.py              # NewsAPI + Finnhub
│   │   └── alpha_vantage_client.py     # Technical indicators
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── schemas.py                  # Pydantic models (AgentSignal, ConsensusSignal)
│   │   ├── base_agent.py              # Base agent class with LangChain setup
│   │   ├── macro_agent.py             # Macro Regime Analyst
│   │   ├── fundamental_agent.py       # Fundamental Analyst
│   │   ├── sentiment_agent.py         # Sentiment & News Analyst
│   │   ├── options_agent.py           # Options Flow Analyst
│   │   ├── quant_agent.py             # Quantitative Strategist
│   │   ├── consensus.py               # Consensus Engine
│   │   ├── orchestrator.py            # LangGraph orchestration
│   │   └── nlp/
│   │       ├── __init__.py
│   │       ├── sentiment.py           # FinBERT + spaCy pipeline
│   │       └── transcript_analyzer.py # Earnings call analysis
│   ├── quant/
│   │   ├── __init__.py
│   │   ├── options_analytics.py       # BSM, Greeks, IV analysis
│   │   ├── technical_indicators.py    # RSI, MACD, Bollinger, etc.
│   │   ├── risk_metrics.py            # VaR, Sharpe, position sizing
│   │   └── backtest.py                # Signal backtesting framework
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py                # SQLAlchemy + asyncpg setup
│   │   └── models.py                  # ORM models
│   └── routes/
│       ├── __init__.py
│       ├── analysis.py                # /api/analyze endpoints
│       ├── data.py                    # /api/data endpoints
│       ├── agents.py                  # /api/agents endpoints
│       ├── portfolio.py               # /api/portfolio endpoints
│       └── websocket.py               # WebSocket handlers
├── frontend/
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                   # Dashboard
│   │   ├── analyze/
│   │   │   └── [ticker]/
│   │   │       └── page.tsx           # Analysis view
│   │   ├── agents/
│   │   │   └── page.tsx               # Agent performance
│   │   ├── portfolio/
│   │   │   └── page.tsx               # Portfolio view
│   │   ├── filings/
│   │   │   └── page.tsx               # SEC filings monitor
│   │   ├── news/
│   │   │   └── page.tsx               # News sentiment feed
│   │   ├── macro/
│   │   │   └── page.tsx               # Macro dashboard
│   │   └── settings/
│   │       └── page.tsx               # Configuration
│   ├── components/
│   │   ├── AgentCard.tsx              # Individual agent signal display
│   │   ├── ConsensusPanel.tsx         # Aggregated consensus view
│   │   ├── ConvictionBar.tsx          # Visual conviction score (0-100)
│   │   ├── MacroRegimeIndicator.tsx   # Regime classification badge
│   │   ├── PriceChart.tsx             # TradingView Lightweight Charts
│   │   ├── SignalTimeline.tsx         # Historical signals timeline
│   │   ├── TradeConsole.tsx           # MD execution panel
│   │   ├── FilingAlert.tsx            # Real-time SEC filing card
│   │   ├── SentimentGauge.tsx         # Sentiment visualization
│   │   ├── PortfolioTable.tsx         # Positions & P&L table
│   │   └── RiskDashboard.tsx          # Portfolio risk metrics
│   ├── lib/
│   │   ├── api.ts                     # API client (fetch wrappers)
│   │   ├── websocket.ts              # WebSocket connection manager
│   │   └── types.ts                  # TypeScript types matching backend schemas
│   └── hooks/
│       ├── useAnalysis.ts             # Analysis state management
│       ├── useWebSocket.ts            # WebSocket hook
│       └── usePortfolio.ts            # Portfolio state
├── railway.toml                       # Railway deployment config
├── docker-compose.yml                 # Local dev (postgres + redis)
├── .env.example                       # Required environment variables
└── README.md
```

---

## 11. ENVIRONMENT VARIABLES

```bash
# .env.example — Copy to .env and fill in values

# LLM
ANTHROPIC_API_KEY=sk-ant-...

# Data Sources
SEC_API_KEY=your-sec-api-key
FRED_API_KEY=your-fred-api-key
NEWS_API_KEY=your-newsapi-key
FINNHUB_API_KEY=your-finnhub-key
ALPHA_VANTAGE_KEY=your-alpha-vantage-key

# Database (Railway provides this automatically)
DATABASE_URL=postgresql://...

# Redis (Railway provides this automatically)
REDIS_URL=redis://...

# App Config
BACKEND_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000
ENV=development
```

---

## 12. PHASED BUILD PLAN

### Phase 1 — Foundation (Weeks 1–3) ← BUILD THIS FIRST

**Goal:** Get one ticker analyzed by all 5 agents with consensus output displayed in the UI.

1. Set up monorepo structure (`backend/` + `frontend/`)
2. Build all 5 data clients (SEC, FRED, Yahoo Finance, NewsAPI, Alpha Vantage)
3. Build `AgentSignal` and `ConsensusSignal` Pydantic schemas
4. Build one agent end-to-end (start with Fundamental Agent — it's the most testable)
5. Build Consensus Engine
6. Build FastAPI `/api/analyze/{ticker}` endpoint
7. Build Next.js analysis page with agent cards and consensus panel
8. Deploy to Railway

**Phase 1 Deliverable:** Enter "AAPL" → see 5 agent cards populate with signals → see consensus recommendation. Screenshot it. Add it to the portfolio site.

### Phase 2 — Intelligence (Weeks 4–6)

- Add FinBERT NLP sentiment pipeline
- Add earnings transcript delta analysis
- Build options analytics module (BSM, Greeks, unusual activity scoring)
- Add macro regime classification model
- Build backtesting framework for signal validation
- Add agent accuracy tracking (did the signal predict correctly?)

### Phase 3 — Real-Time (Weeks 7–9)

- WebSocket integration with sec-api.io for live filing alerts
- Real-time news sentiment streaming
- Automated scheduled analysis runs (daily pre-market scan of watchlist)
- Trade journal and portfolio tracking
- Risk dashboard (portfolio beta, VaR, sector exposure)

### Phase 4 — Execution (Weeks 10–12)

- Broker API integration (Alpaca for paper trading first, then live)
- Position sizing automation
- Stop-loss / take-profit monitoring
- Portfolio rebalancing signals
- Performance attribution (which agent contributed most to P&L)

### Phase 5 — Scale (Months 4–6)

- Multi-tenant architecture for licensing
- Custom agent configuration per user
- API access for institutional clients
- Historical signal database for backtesting as a service
- Mobile alerts (Telegram/SMS for high-conviction signals)

---

## 13. CRITICAL IMPLEMENTATION NOTES FOR CLAUDE CODE

1. **Start with `backend/` first.** Get the data clients and one agent working in isolation before touching the frontend. Test each data client independently with a simple script.

2. **Use `sec-api` Python package** (`pip install sec-api`). It wraps sec-api.io. The PyPI package is maintained and current.

3. **LangChain agent pattern:** Each agent should use `create_react_agent()` from `langchain.agents` with Claude as the LLM. Tools are the data client methods wrapped as `@tool` functions.

4. **Do NOT use OpenAI.** All LLM calls go through Anthropic's Claude API via `langchain-anthropic`. Model: `claude-sonnet-4-20250514`.

5. **FinBERT model:** `ProsusAI/finbert` from HuggingFace. It's ~400MB. For Railway deployment, consider using the transformers pipeline with a smaller model first, then upgrade.

6. **Rate limits matter.** NewsAPI free tier = 100 req/day. sec-api.io free = 100 req/month. FRED = 120 req/min. Yahoo Finance = no official limit but throttles at ~2000/hr. Build caching (Redis) from day one.

7. **The consensus narrative** should be generated by Claude. After collecting all 5 agent signals, send them to Claude with a prompt: "Synthesize these 5 analyst signals into a coherent investment memo. Identify where agents agree, where they disagree, and what the key swing factor is."

8. **Frontend WebSocket pattern:** When the user clicks "Analyze," the frontend opens a WebSocket to `/ws/analysis/{ticker}`. As each agent completes, the backend sends its signal through the socket. The UI updates each agent card from "Analyzing..." to the completed signal in real-time. This creates a compelling "watching the desk work" experience.

9. **PostgreSQL on Railway** auto-provisions. Just add a Postgres plugin to the Railway project and use the `DATABASE_URL` env var.

10. **Deploy backend and frontend as separate Railway services** in the same project. Backend = Python (Dockerfile or Nixpacks auto-detect), Frontend = Node.js.

---

## 14. PORTFOLIO SITE INTEGRATION

This platform should be showcased on the existing portfolio site at `portfolio-production-e865.up.railway.app` as:

**Project Name:** Alpha Engine — AI Quantitative Trading Intelligence Platform
**Tagline:** "A virtual trading desk where 5 specialized AI agents analyze markets and converge through consensus to generate institutional-grade trade intelligence."

**Key Technical Highlights to Feature:**
- Multi-agent AI architecture with LangChain/LangGraph orchestration
- Real-time SEC EDGAR integration (filings within 300ms)
- FinBERT NLP for financial sentiment analysis
- Custom Black-Scholes-Merton pricing engine with Greeks calculation
- Macro regime classification using FRED economic data
- Consensus mechanism producing conviction-scored trade recommendations
- Full-stack: Python (FastAPI) + Next.js (React) + PostgreSQL + Redis
- Deployed on Railway with WebSocket real-time streaming

---

*This document is the single source of truth for the Alpha Engine build. Claude Code should reference this spec for all architectural decisions, naming conventions, and implementation priorities.*
