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
def get_yield_curve_history(lookback_days: int = 90) -> list:
    """Get historical yield curve spread (10Y-2Y). Useful for regime trend analysis."""
    return _fred.get_series_history("T10Y2Y", lookback_days)


@tool
def get_credit_spread_history(lookback_days: int = 90) -> list:
    """Get historical high-yield credit spread (OAS). Widening = risk-off."""
    return _fred.get_series_history("BAMLH0A0HYM2", lookback_days)


@tool
def get_vix_history(lookback_days: int = 90) -> list:
    """Get historical VIX data. Rising VIX = increasing fear."""
    return _fred.get_series_history("VIXCLS", lookback_days)


# === Market Tools ===

@tool
def get_fundamentals(ticker: str) -> dict:
    """Get key fundamentals for a ticker: P/E, P/B, EV/EBITDA, margins, growth,
    debt/equity, FCF, beta, 52-week range, sector, industry, current price."""
    return _market.get_fundamentals(ticker)


@tool
def get_price_history(ticker: str, period: str = "3mo") -> list:
    """Get OHLCV price history. Periods: 1mo, 3mo, 6mo, 1y. Default 3mo."""
    return _market.get_price_history(ticker, period=period)


@tool
def get_options_chain(ticker: str) -> dict:
    """Get nearest-expiry options chain: calls/puts with strike, volume, OI, IV."""
    return _market.get_options_chain(ticker)


# === News Tools ===

@tool
def get_ticker_news(ticker: str) -> list:
    """Get recent news articles for a ticker. Returns title, description, source, date."""
    return _news.get_ticker_news(ticker, page_size=10)


@tool
def get_finnhub_news(ticker: str) -> dict:
    """Get company news from Finnhub with article count and headlines."""
    return _news.get_market_sentiment_finnhub(ticker)


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
    """Score sentiment on recent news for a ticker using financial NLP.
    Returns per-article scores (positive/negative/neutral with confidence)
    and aggregate metrics (bullish %, bearish %, compound score).
    More precise than reading headlines — quantitative sentiment scoring."""
    articles = _news.get_ticker_news(ticker, page_size=10)
    from agents.nlp.sentiment import score_articles
    return score_articles(articles)


# === Options Analytics ===

@tool
def get_options_analysis(ticker: str) -> dict:
    """Get computed options analytics for a ticker: put/call ratio, implied move,
    ATM IV, Greeks, IV skew, max pain, unusual activity detection. This is
    computed math from live options chains — not raw chain data."""
    from quant.options_analytics import analyze_options
    return analyze_options(ticker)


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

OUTPUT_INSTRUCTIONS = """After using your tools to gather data, respond with a single JSON object
matching the schema above. The data_summary field should be a comprehensive 2-4 paragraph narrative
that synthesizes all gathered data with specific numbers and dates cited."""


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
            max_iterations=20,
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
