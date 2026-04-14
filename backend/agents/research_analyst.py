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
    """Get recent news for a ticker. Returns title, source, date. Limited to 5 articles."""
    articles = _news.get_ticker_news(ticker, page_size=5)
    # Return only title and source to minimize tokens
    return [{"title": a.get("title", ""), "source": a.get("source", "")} for a in articles]


@tool
def get_finnhub_news(ticker: str) -> dict:
    """Get company news from Finnhub. Returns article count and top 3 headlines."""
    data = _news.get_market_sentiment_finnhub(ticker)
    # Trim to just count + top 3 headlines to save tokens
    articles = data.get("articles", [])[:3]
    return {
        "article_count": data.get("article_count", 0),
        "top_headlines": [a.get("headline", "")[:80] for a in articles],
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


SYSTEM_PROMPT = """You are a senior research analyst at a quantitative hedge fund. You have been
given an analysis plan and your job is to execute it by gathering all relevant data.

You have access to:
- Macro data (FRED): macro snapshot, yield curve history, credit spread history, VIX history
- Market data (Yahoo Finance): fundamentals, price history, options chains
- News (NewsAPI + Finnhub): ticker news, general market news
- SEC filings: recent filings, insider trades, full-text search
- Technicals (Alpha Vantage): RSI, MACD — USE SPARINGLY (25 calls/day)

IMPORTANT RULES:
1. Execute ONLY the data_requests from the plan. Do not fetch data not asked for.
2. For ticker-specific data, only pull for tickers listed in the plan.
3. Start with macro_snapshot if the plan requests it — it's cached and cheap.
4. Limit NewsAPI calls — 100/day budget. One call per ticker max.
5. Alpha Vantage: only use if specifically needed for technical confirmation.
6. SEC full-text search: use for thematic queries, not per-ticker analysis.
7. Keep options chain calls to 1-2 tickers max.

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

OUTPUT_INSTRUCTIONS = """CRITICAL: You have very limited iterations. Call at MOST 3-4 tools total,
then IMMEDIATELY produce your JSON response. Do NOT try to gather data for every ticker —
prioritize the 2-3 most important data points. Your data_summary narrative is the most
important output — make it 2-3 paragraphs with specific numbers."""


class ResearchAnalyst(BaseAgent):
    agent_name = "research_analyst"
    system_prompt = SYSTEM_PROMPT
    output_instructions = OUTPUT_INSTRUCTIONS

    def __init__(self):
        super().__init__()
        # Research analyst needs more iterations — it makes the most tool calls
        self._max_iterations = 20

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
            max_iterations=5,
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
            get_insider_trades,
            search_filings_fulltext,
            score_news_sentiment,
            get_options_analysis,
            search_web,
            get_rsi,
            get_macd,
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
