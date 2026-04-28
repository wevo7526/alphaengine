"""
Research Analyst — gathers data from all sources based on the analysis plan.

This agent consolidates all data tools from the old 5-agent system into a single
agent that intelligently selects which tools to call based on the plan.
"""

import json
from langchain_core.tools import tool

from agents.base_agent import BaseAgent
from data.fred_client import FREDDataClient
from data.market_client import MarketDataClient
from data.news_client import NewsDataClient
from data.sec_client import SECDataClient
from data.alpha_vantage_client import AlphaVantageClient

_fred = FREDDataClient()
_market = MarketDataClient()
_news = NewsDataClient()
_sec = SECDataClient()
_av = AlphaVantageClient()


# === Macro Tools ===

@tool
def get_macro_snapshot() -> dict:
    """Get all key macroeconomic indicators: fed funds rate, yield curve, credit spreads,
    VIX, unemployment, CPI, GDP, Fed balance sheet, jobless claims, USD index, oil, M2.
    Returns current value, previous value, and change for each."""
    return _fred.get_macro_snapshot()


@tool
def get_yield_curve_history(lookback_days: int = 30) -> list:
    """Get 30-day yield curve spread (10Y-2Y) trend."""
    return _fred.get_series_history("T10Y2Y", lookback_days)


@tool
def get_credit_spread_history(lookback_days: int = 30) -> list:
    """Get 30-day high-yield credit spread trend. Widening = risk-off."""
    return _fred.get_series_history("BAMLH0A0HYM2", lookback_days)


@tool
def get_vix_history(lookback_days: int = 30) -> list:
    """Get 30-day VIX trend. Rising = increasing fear."""
    return _fred.get_series_history("VIXCLS", lookback_days)


# === Market Tools ===

@tool
def get_fundamentals(ticker: str) -> dict:
    """Get key fundamentals: P/E, EV/EBITDA, margins, growth, beta, price, sector."""
    data = _market.get_fundamentals(ticker)
    return {
        "current_price": data.get("current_price"),
        "pe_ratio": data.get("pe_ratio"),
        "forward_pe": data.get("forward_pe"),
        "ev_ebitda": data.get("ev_ebitda"),
        "revenue_growth": data.get("revenue_growth"),
        "profit_margin": data.get("profit_margin"),
        "debt_to_equity": data.get("debt_to_equity"),
        "beta": data.get("beta"),
        "52w_high": data.get("52w_high"),
        "52w_low": data.get("52w_low"),
        "sector": data.get("sector"),
    }


@tool
def get_price_history(ticker: str, period: str = "1mo") -> list:
    """Get OHLCV price history. Periods: 1mo, 3mo, 6mo. Default 1mo to conserve tokens."""
    data = _market.get_price_history(ticker, period=period)
    # Return only last 20 bars — enough for trend analysis without context blowout
    return data[-20:] if len(data) > 20 else data


@tool
def get_options_chain(ticker: str) -> dict:
    """Get nearest-expiry options chain: calls/puts with strike, volume, OI, IV."""
    return _market.get_options_chain(ticker)


# === News Tools ===

@tool
def get_ticker_news(ticker: str) -> list:
    """
    Recent news for a ticker. Returns title + description + source + date for
    the top 5 articles. Description is ~200-400 chars so the LLM can read
    actual content, not just headlines (was: title-only).
    """
    articles = _news.get_ticker_news(ticker, page_size=5)
    return [
        {
            "title": a.get("title", ""),
            "description": (a.get("description") or "")[:500],
            "source": a.get("source", ""),
            "published_at": a.get("published_at") or a.get("publishedAt"),
            "url": a.get("url"),
        }
        for a in articles
    ]


@tool
def get_finnhub_news(ticker: str) -> dict:
    """
    Company news from Finnhub. Returns article count + top 5 headlines with
    summaries (was: 3 truncated headlines).
    """
    data = _news.get_market_sentiment_finnhub(ticker)
    articles = data.get("articles", [])[:5]
    return {
        "article_count": data.get("article_count", 0),
        "articles": [
            {
                "headline": a.get("headline", ""),
                "summary": (a.get("summary") or "")[:400],
                "source": a.get("source"),
                "datetime": a.get("datetime"),
                "url": a.get("url"),
            }
            for a in articles
        ],
    }


@tool
def get_market_news() -> list:
    """Get general market news headlines (not ticker-specific)."""
    return _news.get_market_news_finnhub(category="general")


# === SEC Tools ===

@tool
def get_recent_filings(ticker: str, form_type: str = "8-K", limit: int = 3) -> dict:
    """Get recent SEC filings by type. form_type: 8-K, 10-K, 10-Q. Keep limit low."""
    return _sec.get_recent_filings(ticker, form_type=form_type, limit=limit)


@tool
def get_filing_section(filing_url: str, section: str = "mda") -> dict:
    """
    Pull a specific section from a 10-K / 10-Q filing. `section` is one of:
      "mda"            — Management's Discussion & Analysis
      "risk_factors"   — Item 1A risk factors
      "business"       — Business description
      "financials"     — Financial statements

    Returns the raw text trimmed to 8000 chars (~1500 tokens) so the LLM can
    actually read it. Use SPARINGLY — costs an SEC-API call and large tokens.
    Pass a `filing_url` from get_recent_filings.
    """
    fn_map = {
        "mda": _sec.extract_mda,
        "risk_factors": _sec.extract_risk_factors,
        "business": _sec.extract_business_description,
        "financials": _sec.extract_financial_statements,
    }
    fn = fn_map.get(section.lower())
    if not fn:
        return {"error": f"Unknown section '{section}'. Use: {list(fn_map.keys())}"}
    try:
        text = fn(filing_url) or ""
        return {
            "section": section,
            "filing_url": filing_url,
            "char_count": len(text),
            "text": text[:8000],
            "truncated": len(text) > 8000,
        }
    except Exception as e:
        return {"error": str(e), "section": section}


@tool
def get_insider_trades(ticker: str) -> dict:
    """Get insider trading activity (Forms 3, 4, 5) for a ticker."""
    return _sec.get_insider_trades(ticker)


@tool
def search_filings_fulltext(query_text: str) -> dict:
    """Full-text search across SEC filings. Use for thematic searches like
    'tariff impact', 'AI capital expenditure', 'supply chain disruption'."""
    return _sec.search_filings_fulltext(query_text, form_types=["10-K", "10-Q", "8-K"])


# === Sentiment Scoring ===

@tool
def score_news_sentiment(ticker: str) -> dict:
    """Score sentiment on recent news. Returns aggregate: compound score, bullish/bearish %."""
    articles = _news.get_ticker_news(ticker, page_size=5)
    from agents.nlp.sentiment import score_articles
    result = score_articles(articles)
    # Return only aggregate — per-article scores waste tokens
    return result.get("aggregate", {})


# === Options Analytics ===

@tool
def get_options_analysis(ticker: str) -> dict:
    """Get computed options analytics: put/call ratio, implied move, ATM IV, Greeks."""
    from quant.options_analytics import analyze_options
    data = analyze_options(ticker)
    if "error" in data:
        return data
    # Return only key metrics to conserve tokens
    return {
        "put_call_ratio": data.get("put_call_ratio"),
        "implied_move_pct": data.get("implied_move_pct"),
        "atm_iv": data.get("atm_iv"),
        "iv_skew": data.get("iv_skew"),
        "max_pain": data.get("max_pain"),
        "pc_ratio_signal": data.get("pc_ratio_signal"),
        "greeks": data.get("greeks"),
        # Enriched flow / term-structure signals
        "term_structure": data.get("term_structure"),
        "vol_backwardation": data.get("vol_backwardation"),
        "flow_imbalance": data.get("flow_imbalance"),
        "flow_signal": data.get("flow_signal"),
    }


# === Web Research (Firecrawl) ===

@tool
def search_web(query: str) -> list:
    """Search the web for real-time information to validate or supplement data.
    Use for: earnings results, breaking news, analyst reports, company announcements.
    Returns top 3 results with title, URL, and content excerpt. CONSERVE: use sparingly."""
    from data.firecrawl_client import search_web as _search
    return _search(query, limit=3)


# === Technical Tools ===

@tool
def get_rsi(ticker: str) -> dict:
    """Get RSI (14-period) from Alpha Vantage. CONSERVE: 25 calls/day limit."""
    return _av.get_rsi(ticker)


@tool
def get_macd(ticker: str) -> dict:
    """Get MACD from Alpha Vantage. CONSERVE: 25 calls/day limit."""
    return _av.get_macd(ticker)


# === Earnings calendar / analyst consensus / peer comp / short interest ===

@tool
def get_earnings_calendar(ticker: str) -> dict:
    """
    Verified next earnings date + recent reported quarters for a ticker.
    Use this BEFORE writing 'Q2 earnings July 25' style catalysts so dates
    are tool-grounded, not LLM-guessed.
    """
    return _market.get_earnings_calendar(ticker)


@tool
def get_analyst_consensus(ticker: str) -> dict:
    """
    Sell-side analyst consensus: target price (mean/high/low/median),
    recommendation_key, number of analysts covering, forward EPS,
    revenue growth, and implied upside vs current price.

    Use this to back up 'Street is bullish' / 'beating expectations' claims
    with actual numbers.
    """
    return _market.get_consensus(ticker)


@tool
def get_peer_comparison(ticker: str, peers: str | None = None) -> dict:
    """
    Pull P/E, EV/EBITDA, margin, growth for a ticker AND its sector peers
    so valuation can be assessed in context, not in isolation.

    `peers`: optional comma-separated peer tickers. If omitted, uses a
    default peer set per sector (top 4 mega-caps in the same GICS sector).
    Returns each peer's key ratios + the relative position of `ticker`
    (above/below median for each metric).
    """
    from data.sector_map import resolve_sector
    target_fund = _market.get_fundamentals(ticker)
    target_sector, _ = resolve_sector(ticker, (target_fund or {}).get("sector"))

    # Default peer sets — top mega-caps per GICS sector. Hand-curated so we
    # don't burn API on a dynamic universe scan.
    DEFAULT_PEERS: dict[str, list[str]] = {
        "Technology": ["AAPL", "MSFT", "NVDA", "AVGO"],
        "Communication Services": ["GOOGL", "META", "NFLX", "DIS"],
        "Consumer Cyclical": ["AMZN", "TSLA", "HD", "MCD"],
        "Consumer Defensive": ["WMT", "PG", "COST", "KO"],
        "Healthcare": ["UNH", "JNJ", "LLY", "PFE"],
        "Financial Services": ["JPM", "V", "MA", "BAC"],
        "Industrials": ["BA", "GE", "CAT", "HON"],
        "Energy": ["XOM", "CVX", "COP", "SLB"],
        "Utilities": ["NEE", "SO", "DUK", "AEP"],
        "Real Estate": ["PLD", "AMT", "EQIX", "WELL"],
        "Basic Materials": ["LIN", "SHW", "FCX", "NEM"],
    }

    if peers:
        peer_list = [p.strip().upper() for p in peers.split(",") if p.strip() and p.strip().upper() != ticker.upper()]
    else:
        peer_list = [p for p in DEFAULT_PEERS.get(target_sector, []) if p != ticker.upper()]

    peer_list = peer_list[:4]  # cap at 4 peers — API conservation
    peer_data = {}
    for p in peer_list:
        try:
            f = _market.get_fundamentals(p)
            peer_data[p] = {
                "pe_ratio": f.get("pe_ratio"),
                "forward_pe": f.get("forward_pe"),
                "ev_ebitda": f.get("ev_ebitda"),
                "profit_margin": f.get("profit_margin"),
                "revenue_growth": f.get("revenue_growth"),
                "market_cap": f.get("market_cap"),
            }
        except Exception:
            continue

    if not peer_data:
        return {"ticker": ticker.upper(), "sector": target_sector, "peers": {}, "note": "Peer data unavailable"}

    # Median by metric — flag where target lies
    import statistics as _stats
    metrics = ["pe_ratio", "forward_pe", "ev_ebitda", "profit_margin", "revenue_growth"]
    target_metrics = {m: target_fund.get(m) for m in metrics}
    medians: dict[str, float | None] = {}
    relative: dict[str, str] = {}
    for m in metrics:
        vals = [pd[m] for pd in peer_data.values() if pd.get(m) is not None]
        if vals:
            med = float(_stats.median(vals))
            medians[m] = round(med, 4)
            tv = target_metrics.get(m)
            if tv is not None:
                if m in ("pe_ratio", "forward_pe", "ev_ebitda"):
                    # Lower = cheaper for valuation multiples
                    relative[m] = "cheaper" if tv < med else "richer" if tv > med else "in-line"
                else:
                    # Higher = better for margin/growth
                    relative[m] = "better" if tv > med else "worse" if tv < med else "in-line"
        else:
            medians[m] = None

    return {
        "ticker": ticker.upper(),
        "sector": target_sector,
        "target_metrics": target_metrics,
        "peers": peer_data,
        "peer_medians": medians,
        "relative_to_peers": relative,
    }


@tool
def get_short_interest(ticker: str) -> dict:
    """
    Short interest signal: shortRatio (days-to-cover), float shares, short %
    of float (when available). High short ratio (>5 days) + positive
    earnings surprise = squeeze setup. Negligible short interest with
    weakness = no support coming from short covering.
    """
    f = _market.get_fundamentals(ticker)
    if not f:
        return {"error": f"No fundamentals for {ticker}"}
    short_ratio = f.get("short_ratio")
    float_shares = f.get("float_shares")
    shares_out = f.get("shares_outstanding")
    interpretation = []
    if short_ratio is not None:
        if short_ratio >= 7:
            interpretation.append(f"days-to-cover {short_ratio:.1f} — squeeze risk if catalyst hits")
        elif short_ratio >= 4:
            interpretation.append(f"days-to-cover {short_ratio:.1f} — moderate short interest")
        else:
            interpretation.append(f"days-to-cover {short_ratio:.1f} — light short interest")
    return {
        "ticker": ticker.upper(),
        "short_ratio_days_to_cover": short_ratio,
        "float_shares": float_shares,
        "shares_outstanding": shares_out,
        "short_pct_of_float_estimate": (
            round(short_ratio / 252 * 100, 2) if short_ratio else None
        ),
        "notes": interpretation,
    }


SYSTEM_PROMPT = """You are a senior research analyst at a quantitative hedge fund. You have been
given an analysis plan and your job is to execute it by gathering all relevant data.

You have access to:
- Macro data (FRED): macro snapshot, yield curve history, credit spread history, VIX history
- Market data (Yahoo Finance): fundamentals, price history, options chains
- News (NewsAPI + Finnhub): ticker news, general market news
- SEC filings: recent filings, insider trades, full-text search
- Technicals (Alpha Vantage): RSI, MACD — USE SPARINGLY (25 calls/day)
- Catalyst grounding: get_earnings_calendar (verified next earnings date),
  get_analyst_consensus (target prices, recommendation_key, forward EPS)
- Relative valuation: get_peer_comparison (target vs sector peers' P/E,
  margin, growth — call ONCE per primary ticker)
- Crowding: get_short_interest (days-to-cover, short %)

IMPORTANT RULES:
1. Execute ONLY the data_requests from the plan. Do not fetch data not asked for.
2. For ticker-specific data, only pull for tickers listed in the plan.
3. Start with macro_snapshot if the plan requests it — it's cached and cheap.
4. Limit NewsAPI calls — 100/day budget. One call per ticker max.
5. Alpha Vantage: only use if specifically needed for technical confirmation.
6. SEC full-text search: use for thematic queries, not per-ticker analysis.
7. Keep options chain calls to 1-2 tickers max.
8. ALWAYS call get_earnings_calendar before writing earnings-date catalysts.
9. Use get_analyst_consensus for any "Street is bullish/bearish" claim.
10. Use get_peer_comparison instead of judging valuation in isolation.

After gathering data, produce a JSON summary with:
{{
    "macro_data": {{...}},
    "ticker_data": {{"AAPL": {{"fundamentals": {{...}}, "price_summary": "...", "news_summary": "..."}}, ...}},
    "news_data": [{{...}}],
    "filing_data": [{{...}}],
    "thematic_data": {{"key_findings": [...]}},
    "data_summary": "<narrative summary of all data gathered, citing specific numbers>"
}}

The data_summary is critical — it's what downstream agents (Risk Manager, Portfolio Strategist)
will primarily read. Make it thorough, quantitative, and specific."""

OUTPUT_INSTRUCTIONS = """You have up to 10 tool calls. Use them efficiently:
- Call macro_snapshot first (1 call, covers all macro data).
- Batch ticker research: fundamentals + news per ticker (2 calls each).
- For 4 tickers: ~9 calls total. Prioritize the top 3-4 tickers.
- Skip Alpha Vantage unless specifically needed — RSI/MACD can be inferred from price history.

After gathering data, produce your JSON response immediately. Your data_summary narrative
is the most important output — make it 3-4 paragraphs with specific numbers from the data."""


class ResearchAnalyst(BaseAgent):
    agent_name = "research_analyst"
    system_prompt = SYSTEM_PROMPT
    output_instructions = OUTPUT_INSTRUCTIONS

    def _build_executor(self):
        from langchain.agents import create_tool_calling_agent, AgentExecutor
        from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

        tools = self.get_tools()
        prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt + "\n\n" + self.output_instructions),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        agent = create_tool_calling_agent(self.llm, tools, prompt)
        return AgentExecutor(
            agent=agent, tools=tools, verbose=False,
            max_iterations=12,
            handle_parsing_errors=True,
        )

    def get_tools(self):
        return [
            get_macro_snapshot,
            get_yield_curve_history,
            get_credit_spread_history,
            get_vix_history,
            get_fundamentals,
            get_price_history,
            get_options_chain,
            get_ticker_news,
            get_finnhub_news,
            get_market_news,
            get_recent_filings,
            get_filing_section,
            get_insider_trades,
            search_filings_fulltext,
            score_news_sentiment,
            get_options_analysis,
            search_web,
            get_rsi,
            get_macd,
            # New: tool-ground catalysts, valuation context, and crowding
            get_earnings_calendar,
            get_analyst_consensus,
            get_peer_comparison,
            get_short_interest,
        ]

    def build_input_prompt(self, context: dict) -> str:
        plan = context.get("plan", {})
        return (
            f"Execute the following research plan:\n\n"
            f"Query: {plan.get('query', '')}\n"
            f"Intent: {plan.get('intent', '')}\n"
            f"Tickers: {', '.join(plan.get('tickers', []))}\n"
            f"Sectors: {', '.join(plan.get('sectors', []))}\n"
            f"Themes: {', '.join(plan.get('themes', []))}\n"
            f"Time Horizon: {plan.get('time_horizon', 'weeks')}\n\n"
            f"Data Requests:\n" +
            "\n".join(f"  - {r}" for r in plan.get("data_requests", [])) +
            "\n\nGather the requested data using your tools, then produce your JSON summary."
        )
