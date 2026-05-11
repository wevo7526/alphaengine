"""
infra/lineage.py — Provenance extraction from agent tool-call history.

What this is: every memo carries a `lineage` block — a structured list of
every tool call that produced data for it. A PM auditing a number in a
memo can open the lineage panel and see "this number came from
get_fundamentals(AAPL) returned at time T" with a clickable source link
(SEC accession, FRED series ID, ticker+date for market data, fund CIK
for 13F).

What this is NOT: a magic AI fact-checker. We do not run an LLM to match
every numeric claim back to a tool call — that's expensive, brittle, and
gives a false sense of precision. We instead capture the entire tool-call
history and let the PM eyeball it. This is the same approach Bloomberg
uses on its Securities pages — show all the sources, let the analyst
judge.

Source-type taxonomy (used by the UI for grouping):
    sec_filing       — SEC EDGAR filings (Forms 8-K, 10-K, 10-Q, 13F, etc.)
    sec_insider      — Form 4 insider transactions
    sec_13f          — 13F institutional holdings
    fred_series      — Federal Reserve Economic Data series
    market_price     — Equity/ETF prices, fundamentals, options (yfinance)
    news_article     — NewsAPI or Finnhub news articles
    web_search       — Firecrawl scraped pages
    technical        — Alpha Vantage RSI/MACD/etc.
    screen           — Dynamic screens (insider clusters, 13F initiations, etc.)
    computed         — Pair analysis, factor regressions, etc.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# Map tool function names to source types. Keep in sync with the @tool
# decorators in agents/research_analyst.py and agents/risk_manager.py.
TOOL_SOURCE_TYPE: dict[str, str] = {
    # Macro / FRED
    "get_macro_snapshot": "fred_series",
    "get_yield_curve_history": "fred_series",
    "get_credit_spread_history": "fred_series",
    "get_vix_history": "fred_series",
    # Market data
    "get_fundamentals": "market_price",
    "get_price_history": "market_price",
    "get_options_chain": "market_price",
    "get_options_analysis": "market_price",
    "get_short_interest": "market_price",
    "get_earnings_calendar": "market_price",
    "get_analyst_consensus": "market_price",
    "get_peer_comparison": "market_price",
    "get_current_price": "market_price",
    "get_recent_prices": "market_price",
    # SEC filings
    "get_recent_filings": "sec_filing",
    "get_filing_section": "sec_filing",
    "search_filings_fulltext": "sec_filing",
    "get_insider_trades": "sec_insider",
    # News
    "get_ticker_news": "news_article",
    "get_finnhub_news": "news_article",
    "get_market_news": "news_article",
    "score_news_sentiment": "news_article",
    # Web / technical
    "search_web": "web_search",
    "get_rsi": "technical",
    "get_macd": "technical",
    # Risk Manager tools
    "get_realized_correlation": "computed",
    "get_factor_loadings": "computed",
    "get_market_breadth": "computed",
    "get_upcoming_macro_events": "computed",
    # Screens (Phase B)
    "screen_secondary_universe": "screen",
    "run_insider_cluster_screen": "screen",
    "run_13f_initiation_screen": "screen",
    "run_post_earnings_drift_screen": "screen",
    "run_52w_low_insider_screen": "screen",
    "run_sector_adjacent_screen": "screen",
    # Quant
    "analyze_pair_candidate": "computed",
}


def _coerce_str(v: Any, max_len: int = 200) -> str:
    """Safe string coercion with a length cap to keep lineage payloads small."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v[:max_len]
    try:
        return json.dumps(v, default=str)[:max_len]
    except (TypeError, ValueError):
        return str(v)[:max_len]


def _extract_source_ids(tool_name: str, tool_input: dict, tool_output: Any) -> list[dict[str, str]]:
    """
    Reach into a tool's output and pull canonical source identifiers
    (SEC accession numbers, FRED series IDs, etc.). Returns a list of
    {type, id, url?} dicts. Empty list when nothing identifiable came back.

    All extraction is defensive — tool outputs vary in shape across SDKs
    and free-tier responses sometimes return error dicts.
    """
    sources: list[dict[str, str]] = []
    if tool_output is None:
        return sources

    # SEC filings — `filings: [{accessionNo, linkToFilingDetails, ...}]`
    if tool_name in ("get_recent_filings", "search_filings_fulltext", "get_filing_section"):
        if isinstance(tool_output, dict):
            filings = tool_output.get("filings") or []
            for f in filings[:5] if isinstance(filings, list) else []:
                acc = f.get("accessionNo") or f.get("accessionNumber")
                url = f.get("linkToFilingDetails") or f.get("link") or ""
                form_type = f.get("formType") or ""
                if acc:
                    sources.append({
                        "type": "sec_filing",
                        "id": str(acc),
                        "form_type": str(form_type),
                        "url": str(url),
                    })

    # Insider trades — `data: [{accessionNo, ...}]`
    if tool_name == "get_insider_trades":
        if isinstance(tool_output, dict):
            data = tool_output.get("data") or []
            for f in data[:5] if isinstance(data, list) else []:
                acc = f.get("accessionNo") or f.get("accessionNumber")
                if acc:
                    sources.append({"type": "sec_insider", "id": str(acc), "url": ""})

    # FRED — single-indicator returns {series_id, value, date} (we tag from input args)
    if tool_name in ("get_macro_snapshot", "get_yield_curve_history",
                     "get_credit_spread_history", "get_vix_history"):
        series_arg = tool_input.get("series_id") if isinstance(tool_input, dict) else None
        if series_arg:
            sources.append({
                "type": "fred_series",
                "id": str(series_arg),
                "url": f"https://fred.stlouisfed.org/series/{series_arg}",
            })
        # Macro snapshot returns multiple series — capture all of them
        if tool_name == "get_macro_snapshot" and isinstance(tool_output, dict):
            for key, val in tool_output.items():
                if isinstance(val, dict) and val.get("series_id"):
                    sid = str(val["series_id"])
                    sources.append({
                        "type": "fred_series",
                        "id": sid,
                        "url": f"https://fred.stlouisfed.org/series/{sid}",
                    })

    # Market data — tag with the ticker from the tool_input
    if tool_name in ("get_fundamentals", "get_price_history", "get_options_chain",
                     "get_options_analysis", "get_short_interest",
                     "get_earnings_calendar", "get_analyst_consensus",
                     "get_peer_comparison", "get_current_price", "get_recent_prices"):
        ticker = tool_input.get("ticker") if isinstance(tool_input, dict) else None
        if ticker:
            sources.append({
                "type": "market_price",
                "id": f"{ticker}@yfinance",
                "ticker": str(ticker),
                "url": f"https://finance.yahoo.com/quote/{ticker}",
            })

    # News articles — extract URLs
    if tool_name == "get_ticker_news":
        if isinstance(tool_output, list):
            for art in tool_output[:5]:
                if isinstance(art, dict) and art.get("url"):
                    sources.append({
                        "type": "news_article",
                        "id": _coerce_str(art.get("title"), 80),
                        "url": str(art["url"]),
                    })

    # Screens — capture evidence array from the screen output (Phase B)
    if tool_name in ("run_insider_cluster_screen", "run_13f_initiation_screen",
                     "run_post_earnings_drift_screen", "run_52w_low_insider_screen",
                     "run_sector_adjacent_screen"):
        if isinstance(tool_output, dict):
            candidates = tool_output.get("candidates") or []
            for c in candidates[:10] if isinstance(candidates, list) else []:
                ticker = c.get("ticker") if isinstance(c, dict) else None
                screen_name = c.get("screen") if isinstance(c, dict) else None
                if ticker and screen_name:
                    sources.append({
                        "type": "screen",
                        "id": f"{ticker}@{screen_name}",
                        "ticker": str(ticker),
                        "screen": str(screen_name),
                        "url": "",
                    })
                # Pull through nested screen evidence (SEC accession #s, fund CIKs)
                for ev in (c.get("evidence") if isinstance(c, dict) else None) or []:
                    if isinstance(ev, dict):
                        ev_type = ev.get("type", "")
                        ev_acc = ev.get("accession_number") or ev.get("source_id")
                        ev_cik = ev.get("cik")
                        if ev_acc:
                            sources.append({
                                "type": "sec_filing" if "form" in ev_type.lower() else "sec_13f",
                                "id": str(ev_acc),
                                "url": "",
                            })
                        if ev_cik:
                            sources.append({
                                "type": "sec_13f",
                                "id": f"CIK:{ev_cik}",
                                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ev_cik}",
                            })

    return sources


def extract_tool_lineage(
    intermediate_steps_per_agent: dict[str, list[Any]],
) -> dict[str, Any]:
    """
    Build a `lineage` block from one or more agents' intermediate-steps history.

    `intermediate_steps_per_agent` maps agent_name → list of LangChain
    AgentAction tuples (action, observation). LangChain returns a list of
    (AgentAction, observation_obj). We pull tool name + tool_input from the
    action and tool_output from the observation.

    Returns:
      {
        "sources": [{type, id, url, agent, tool, tool_args, timestamp}, ...],
        "by_tool": {tool_name: count, ...},
        "by_source_type": {source_type: count, ...},
        "by_agent": {agent_name: tool_call_count, ...},
        "n_tool_calls": int,
        "n_unique_sources": int,
        "generated_at": ISO timestamp,
      }

    Deduplicates sources by (type, id). When a source appears multiple times,
    only the first occurrence is kept in `sources` but counters still reflect
    the total tool-call traffic.
    """
    now = datetime.now(timezone.utc).isoformat()
    sources: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    by_tool: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_agent: dict[str, int] = {}
    n_tool_calls = 0

    for agent_name, steps in (intermediate_steps_per_agent or {}).items():
        if not steps:
            continue
        for step in steps:
            # LangChain step shapes:
            #   (AgentAction(tool, tool_input, log), observation)
            #   AgentAction object has .tool, .tool_input attributes
            try:
                if isinstance(step, tuple) and len(step) >= 2:
                    action = step[0]
                    observation = step[1]
                else:
                    continue
                tool_name = getattr(action, "tool", None) or ""
                tool_input = getattr(action, "tool_input", None) or {}
                if not isinstance(tool_input, dict):
                    tool_input = {"input": tool_input}
            except (AttributeError, TypeError, IndexError):
                continue

            if not tool_name:
                continue

            n_tool_calls += 1
            by_tool[tool_name] = by_tool.get(tool_name, 0) + 1
            by_agent[agent_name] = by_agent.get(agent_name, 0) + 1

            source_type = TOOL_SOURCE_TYPE.get(tool_name, "other")
            by_type[source_type] = by_type.get(source_type, 0) + 1

            # Extract canonical source IDs from the tool's output
            try:
                extracted = _extract_source_ids(tool_name, tool_input, observation)
            except Exception as e:  # noqa: BLE001 — defensive against varied SDK shapes
                logger.debug(f"lineage extract failed for {tool_name}: {e}")
                extracted = []

            # Always store at least a stub source for the tool call itself
            if not extracted:
                stub_id = _coerce_str(tool_input, 100)
                extracted = [{"type": source_type, "id": stub_id, "url": ""}]

            for src in extracted:
                key = (src.get("type", "other"), src.get("id", ""))
                if key in seen_keys or not key[1]:
                    continue
                seen_keys.add(key)
                sources.append({
                    **src,
                    "agent": agent_name,
                    "tool": tool_name,
                    "tool_args": _coerce_str(tool_input, 200),
                    "timestamp": now,
                })

    return {
        "sources": sources,
        "by_tool": by_tool,
        "by_source_type": by_type,
        "by_agent": by_agent,
        "n_tool_calls": int(n_tool_calls),
        "n_unique_sources": len(sources),
        "generated_at": now,
    }


def empty_lineage() -> dict[str, Any]:
    """Default empty lineage block — used when no tool history is available."""
    return {
        "sources": [],
        "by_tool": {},
        "by_source_type": {},
        "by_agent": {},
        "n_tool_calls": 0,
        "n_unique_sources": 0,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
