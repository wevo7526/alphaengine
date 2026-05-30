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

    peer_list = peer_list[:3]  # cap at 3 peers — API conservation + token budget
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
def screen_secondary_universe(
    sectors: str = "",
    themes: str = "",
    exclude: str = "",
    cap: int = 50,
) -> dict:
    """
    SCAN THE LIVE MARKET for non-consensus candidates to break Mag7 monoculture.

    Runs real-time screeners (yfinance EquityQuery small/mid-cap scans by
    sector + Alpha Vantage top-movers + predefined style screens) and returns
    up to `cap` under-covered tickers with live facts (market cap, price,
    sector). This is genuine market discovery — NOT a filter over a hardcoded
    list. Mega-caps and excluded names are dropped automatically.

    Args:
      sectors: comma-separated sector names (e.g. "Technology,Healthcare")
      themes:  comma-separated style/theme keys (small_cap, momentum, value,
               growth, contrarian, ...) — drives which predefined screens run
      exclude: comma-separated tickers to skip (typically the primary `tickers`)
      cap: max candidates to return (default 50 — cast a wide net)

    Use this BEFORE writing trade ideas. The desk hires you to find alpha —
    surface names the user hasn't heard of, not consensus mega-cap longs.
    """
    from data.market_screener import screen_market
    sec_list = [s.strip() for s in (sectors or "").split(",") if s.strip()]
    style_list = [t.strip() for t in (themes or "").split(",") if t.strip()]
    excl = [e.strip().upper() for e in (exclude or "").split(",") if e.strip()]
    cands = screen_market(sectors=sec_list, styles=style_list, exclude=excl, cap=cap)
    return {
        "sectors_used": sec_list,
        "styles_used": style_list,
        "candidates": [c["ticker"] for c in cands],
        "candidate_facts": cands[:cap],   # live market cap / price / sector
        "count": len(cands),
        "source": "live_market_scan",
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


@tool
def analyze_pair_candidate(ticker_a: str, ticker_b: str, period: str = "1y") -> dict:
    """
    Run a full pair-trade cointegration analysis on two tickers. Returns
    hedge ratio (Total Least Squares on log prices), Engle-Granger ADF
    p-value, Ornstein-Uhlenbeck mean-reversion half-life in days, current
    spread z-score, and rolling-correlation stability score.

    A pair is `cointegrated=True` only when ALL FOUR pass:
      - ADF p-value < 0.05 (reject unit-root null)
      - 1 < half_life < 60 days (reverts on a tradable horizon)
      - stability > 0.5 (rolling correlation is structurally stable)
      - ≥126 observations (~6 months daily)

    Use this BEFORE proposing any TradeIdea with structure_type='pair'.
    The returned `trade_signal` field tells you whether the current
    z-score is wide enough to enter (long_spread/short_spread) or not (hold).
    `share_ratio_at_close` converts the log-price hedge ratio into a
    share ratio at current prices for execution sizing.
    """
    from quant.pairs import analyze_pair
    return analyze_pair(ticker_a, ticker_b, period=period)


# ─── Hidden-gem discovery screens ────────────────────────────────────────
# Each tool wraps a screen from data.screens; they all return a list of
# candidates with structured `evidence` and plain-English `reasons` so the
# Strategist can cite specific receipts (SEC accession #s, fund CIKs, etc.).

@tool
def run_insider_cluster_screen(
    tickers: str,
    lookback_days: int = 30,
    min_unique_buyers: int = 3,
) -> dict:
    """
    Find tickers with cluster insider buying — at least `min_unique_buyers`
    distinct insiders making open-market Form-4 purchases in the last
    `lookback_days`. CEO/CFO buys weighted 2x.

    `tickers`: comma-separated list of tickers to scan (e.g., "PLTR,DDOG,NET").
    Returns {candidates: [...], n_candidates, screen_params}.
    Use this for thematic queries where you want to find names with strong
    inside-money conviction beyond consensus picks.
    """
    from data.screens import screen_insider_clusters
    universe = [t.strip().upper() for t in (tickers or "").split(",") if t.strip()]
    if not universe:
        return {"candidates": [], "n_candidates": 0, "error": "no tickers provided"}
    candidates = screen_insider_clusters(
        universe=universe,
        lookback_days=lookback_days,
        min_unique_buyers=min_unique_buyers,
    )
    return {
        "candidates": candidates[:15],
        "n_candidates": len(candidates),
        "screen_params": {
            "lookback_days": lookback_days,
            "min_unique_buyers": min_unique_buyers,
        },
    }


@tool
def run_13f_initiation_screen(
    min_position_pct: float = 0.01,
    min_funds_initiating: int = 1,
) -> dict:
    """
    Find names newly initiated by smart-money funds in their latest 13F
    (vs prior quarter's 13F). Smart-money fund list is curated in
    data/smart_money.py (Berkshire, Pershing, Tiger Global, Akre, Baupost,
    Greenlight, Third Point, Glenview, Coatue, Pabrai, etc.).

    `min_position_pct`: minimum size of position as fraction of fund's book
    to count as a meaningful initiation (default 1%).
    `min_funds_initiating`: filter out names initiated by only one fund (set
    to 2 for higher-conviction multi-fund signal).

    13F data has a 45-day lag — these aren't real-time. The value is in
    surfacing names not yet in consensus headlines. Returns {candidates,
    n_candidates, screen_params}.
    """
    from data.screens import screen_13f_new_initiations
    candidates = screen_13f_new_initiations(
        min_position_pct=min_position_pct,
        min_funds_initiating=min_funds_initiating,
    )
    return {
        "candidates": candidates[:15],
        "n_candidates": len(candidates),
        "screen_params": {
            "min_position_pct": min_position_pct,
            "min_funds_initiating": min_funds_initiating,
        },
    }


@tool
def run_post_earnings_drift_screen(
    tickers: str,
    min_surprise_pct: float = 15.0,
    max_analyst_count: int = 10,
) -> dict:
    """
    Find post-earnings-announcement drift (PEAD) candidates: companies that
    beat earnings estimates by ≥`min_surprise_pct` with thin analyst coverage
    (≤`max_analyst_count`). PEAD is strongest in under-covered names —
    classic hidden-gem screen.

    `tickers`: comma-separated list to scan (e.g., "PLTR,DDOG,NET,CRWD").
    Returns {candidates, n_candidates, screen_params}.
    """
    from data.screens import screen_post_earnings_drift
    universe = [t.strip().upper() for t in (tickers or "").split(",") if t.strip()]
    if not universe:
        return {"candidates": [], "n_candidates": 0, "error": "no tickers provided"}
    candidates = screen_post_earnings_drift(
        universe=universe,
        min_surprise_pct=min_surprise_pct,
        max_analyst_count=max_analyst_count,
    )
    return {
        "candidates": candidates[:15],
        "n_candidates": len(candidates),
        "screen_params": {
            "min_surprise_pct": min_surprise_pct,
            "max_analyst_count": max_analyst_count,
        },
    }


@tool
def run_52w_low_insider_screen(
    tickers: str,
    within_pct: float = 5.0,
    insider_lookback_days: int = 30,
) -> dict:
    """
    Turnaround / contrarian setup: price within `within_pct` of 52-week
    low AND insider buying in the last `insider_lookback_days`. The
    insider-buy filter is critical — without it the 52w-low screen is a
    value-trap factory.

    `tickers`: comma-separated list to scan.
    Returns {candidates, n_candidates, screen_params}.
    """
    from data.screens import screen_52w_low_with_insider_buys
    universe = [t.strip().upper() for t in (tickers or "").split(",") if t.strip()]
    if not universe:
        return {"candidates": [], "n_candidates": 0, "error": "no tickers provided"}
    candidates = screen_52w_low_with_insider_buys(
        universe=universe,
        within_pct=within_pct,
        insider_lookback_days=insider_lookback_days,
    )
    return {
        "candidates": candidates[:15],
        "n_candidates": len(candidates),
        "screen_params": {
            "within_pct": within_pct,
            "insider_lookback_days": insider_lookback_days,
        },
    }


@tool
def run_sector_adjacent_screen(theme: str) -> dict:
    """
    Return picks-and-shovels names for a known theme. No API calls — uses
    a curated mapping from data.screens.SECTOR_ADJACENT.

    Available themes include: ai_capex, ai_inference, energy_transition,
    obesity_glp1, data_centers_power, cybersecurity, uranium_nuclear,
    fintech_disruptors, regional_banks.

    Use this when the user query mentions one of these themes — surfaces
    the non-obvious beneficiaries (e.g., for ai_capex returns VRT cooling,
    ETN power, COHR optical, VST/TLN/CEG nuclear) rather than the
    consensus mega-cap names.
    """
    from data.screens import screen_sector_adjacent_to_theme
    candidates = screen_sector_adjacent_to_theme(theme=theme)
    return {
        "candidates": candidates,
        "n_candidates": len(candidates),
        "theme": theme,
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
2. For ticker-specific data, pull for tickers listed in the plan AND for high-conviction
   names from screen_secondary_universe (see rule 11 below).
3. Start with macro_snapshot if the plan requests it — it's cached and cheap.
4. Limit NewsAPI calls — 100/day budget. One call per ticker max.
5. Alpha Vantage: only use if specifically needed for technical confirmation.
6. SEC full-text search: use for thematic queries, not per-ticker analysis.
7. Keep options chain calls to 1-2 tickers max.
8. ALWAYS call get_earnings_calendar before writing earnings-date catalysts.
9. Use get_analyst_consensus for any "Street is bullish/bearish" claim.
10. Use get_peer_comparison instead of judging valuation in isolation.

11. *** WIDER-NET MANDATE *** — A hedge fund desk doesn't pay you to echo
    consensus mega-cap longs back. CALL `screen_secondary_universe` early
    in your run (use sectors + themes from the plan) to surface non-Mag7
    candidates. Then run `get_fundamentals` on 2-3 of those candidates.
    Your data_summary MUST mention at least 2 non-mega-cap tickers as
    candidates with a specific quantitative observation about each.

12. *** STYLE LABELING *** — For EVERY ticker you analyze (primary OR
    secondary), populate `ticker_data[ticker]["style_label"]` with one of:
       growth | value | quality | momentum | low_vol | gard
       defensive | cyclical | special_situation | event_driven | macro
       contrarian | mean_reversion | secular_winner | spinoff | small_cap
       international | yield | hedge | volatility
    AND populate `ticker_data[ticker]["market_cap_bucket"]` with one of:
       mega_cap (>$200B) | large_cap ($50-200B) | mid_cap ($10-50B)
       small_cap ($2-10B) | micro_cap (<$2B) | etf
    These labels are consumed by the Strategist to enforce style diversity.

13. *** HIDDEN-GEM DISCOVERY *** — On any query where the plan's
    `discovery_aggressiveness` is "high" OR the slate target is 8+ ideas,
    you MUST call AT LEAST TWO of the following discovery screens before
    drafting candidates:
       - run_insider_cluster_screen(tickers="...")
            → cluster Form-4 buys, CEO/CFO weighted
       - run_13f_initiation_screen()
            → smart-money funds initiating new positions (Berkshire,
              Pershing, Akre, Coatue, etc.)
       - run_post_earnings_drift_screen(tickers="...")
            → big earnings surprise + thin analyst coverage (PEAD)
       - run_52w_low_insider_screen(tickers="...")
            → contrarian setups with insider conviction
       - run_sector_adjacent_screen(theme="...")
            → curated picks-and-shovels for known themes
    For any name you propose to the Strategist as a discovery candidate,
    record its `screen_source` in ticker_data so the Strategist can claim
    Tier-4 (special situation) status on it.

14. *** TIER COMPLIANCE *** — The Strategist runs a structural gate on
    slates of 8+ ideas: at most 30% Tier-1 (mega-cap, market_cap > $200B)
    AND at least 30% Tier-3/4 (small-cap by market_cap_bucket, or
    `screen_source` set from any discovery screen). Your ticker_data must
    include enough Tier-3/4 candidates to satisfy this gate — otherwise
    the Strategist will reject its own first draft and re-prompt, wasting
    tool budget downstream.

After gathering data, produce a JSON summary with:
{{
    "macro_data": {{...}},
    "ticker_data": {{"AAPL": {{"fundamentals": {{...}}, "price_summary": "...", "news_summary": "...", "style_label": "growth", "market_cap_bucket": "mega_cap"}}, ...}},
    "news_data": [{{...}}],
    "filing_data": [{{...}}],
    "thematic_data": {{"key_findings": [...]}},
    "secondary_candidates_evaluated": ["TICK1", "TICK2", ...],  # the non-mega-cap tickers you actually examined
    "data_summary": "<narrative summary of all data gathered, citing specific numbers AND naming at least 2 non-mega-cap candidates>"
}}

The data_summary is critical — it's what downstream agents (Risk Manager, Portfolio Strategist)
will primarily read. Make it thorough, quantitative, and specific."""

OUTPUT_INSTRUCTIONS = """TOOL BUDGET: 18 tool calls MAX. Plan deliberately.

Suggested allocation for a typical alpha-finding query (3-4 primary tickers
+ wider net + ≥2 discovery screens):
  1  macro_snapshot
  1  screen_secondary_universe (CRITICAL — surfaces non-Mag7 candidates)
  2  discovery screens (insider/13F/PEAD/52w-low/sector-adjacent — pick 2)
  3-4 fundamentals on primary tickers
  2-3 fundamentals on top secondary + screen candidates
  2  news (primary + 1 secondary or screen-surfaced name)
  1  get_earnings_calendar on the primary ticker
  1  get_analyst_consensus on the primary ticker
  1  get_peer_comparison on the primary ticker
  1  get_options_analysis on the primary ticker
  1  buffer for SEC filings, short interest, or pair analysis

Hard rules:
  - You MUST call screen_secondary_universe at least once.
  - You MUST call AT LEAST TWO discovery screens (run_insider_cluster_screen,
    run_13f_initiation_screen, run_post_earnings_drift_screen,
    run_52w_low_insider_screen, run_sector_adjacent_screen) when the plan's
    discovery_aggressiveness is "high" OR slate target is 8+ ideas.
  - You MUST run get_fundamentals on at least 2 secondary (non-mega-cap)
    candidates and report their style_label + market_cap_bucket in ticker_data.
  - For ANY name surfaced by a discovery screen, record `screen_source`
    in ticker_data so the Strategist can tag it as Tier-4 (special situation).
  - Skip Alpha Vantage unless specifically needed (25/day budget).
  - Skip get_filing_section unless thesis requires reading actual filing prose.

After 18 tool calls, STOP and emit JSON. Your data_summary is the critical
output — 4-5 paragraphs, every number sourced from a tool call, AND it MUST
name at least 2 non-mega-cap tickers as alpha candidates with a specific
quantitative observation per name, citing screen evidence when applicable
(e.g., "screen_insider_clusters surfaced TICKER with 4 unique buyers totaling $X")."""


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
            max_iterations=19,  # 18 tool calls + final synthesis pass
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
            screen_secondary_universe,
            analyze_pair_candidate,
            # Hidden-gem discovery screens (Phase B). These are L/S-grade
            # screens that surface non-consensus alpha candidates from SEC
            # data with structured evidence per candidate.
            run_insider_cluster_screen,
            run_13f_initiation_screen,
            run_post_earnings_drift_screen,
            run_52w_low_insider_screen,
            run_sector_adjacent_screen,
        ]

    def build_input_prompt(self, context: dict) -> str:
        plan = context.get("plan", {})

        # Pull the rich Phase-2 fields. data_priority supersedes the legacy
        # data_requests when present.
        priority_items = plan.get("data_priority") or []
        sub_questions = plan.get("sub_questions") or []
        comparison_set = plan.get("comparison_set") or []
        question_type = plan.get("question_type") or ""
        theme_decomp = plan.get("theme_decomposition") or {}
        falsification = plan.get("falsification_criteria") or []
        benchmark = plan.get("benchmark") or ""

        # Format data_priority by rank — the Analyst allocates tools accordingly
        priority_block = ""
        if priority_items:
            buckets: dict[int, list[str]] = {1: [], 2: [], 3: [], 4: []}
            for item in priority_items:
                if not isinstance(item, dict):
                    continue
                rk = int(item.get("rank") or 3)
                rk = max(1, min(4, rk))
                src = item.get("data_source") or ""
                qry = item.get("query") or ""
                jus = item.get("justification") or ""
                buckets[rk].append(f"  [{src}] {qry}  ({jus})")
            priority_lines = []
            for rk in (1, 2, 3, 4):
                if not buckets[rk]:
                    continue
                if rk == 4:
                    priority_lines.append(f"\n  RANK 4 (SKIP — do NOT call these):")
                else:
                    priority_lines.append(f"\n  RANK {rk}{' (CRITICAL)' if rk == 1 else ''}:")
                priority_lines.extend(buckets[rk])
            priority_block = "\n=== DATA PRIORITY (allocate budget by rank) ===" + "".join(priority_lines)

        sub_q_block = ""
        if sub_questions:
            sub_q_block = (
                "\n=== SUB-QUESTIONS YOU MUST ANSWER ===\n"
                "Your data_summary MUST address each of these explicitly. "
                "If you can't answer one, say so and explain why.\n"
                + "\n".join(f"  Q{i+1}: {q}" for i, q in enumerate(sub_questions))
            )

        comparison_block = ""
        if comparison_set:
            comparison_block = (
                f"\n=== COMPARISON SET (peers for relative valuation, NOT trade candidates) ===\n"
                f"  {', '.join(comparison_set)}\n"
                "Call get_peer_comparison with these as the peer list to anchor valuation context."
            )

        theme_block = ""
        if theme_decomp:
            lines = []
            for theme, subs in theme_decomp.items():
                if isinstance(subs, list):
                    lines.append(f"  {theme}: {', '.join(subs)}")
            if lines:
                theme_block = "\n=== THEME DECOMPOSITION (structure your data_summary around these) ===\n" + "\n".join(lines)

        falsification_block = ""
        if falsification:
            falsification_block = (
                "\n=== FALSIFICATION CRITERIA (look for evidence pro/con) ===\n"
                + "\n".join(f"  - {c}" for c in falsification)
            )

        # Legacy fallback: if no data_priority was emitted, fall back to old free-text
        legacy_requests_block = ""
        if not priority_items and plan.get("data_requests"):
            legacy_requests_block = (
                "\nData Requests (legacy free-text):\n"
                + "\n".join(f"  - {r}" for r in plan.get("data_requests", []))
            )

        # User context — anchors the framing to the user's actual book
        # (size, role, mandate, benchmark). Empty string when not provided
        # so old callers continue to work without any change.
        from infra.user_context import _format_user_context_block
        user_block = _format_user_context_block(context.get("user_context"))

        return (
            f"Execute the following research plan:\n\n"
            f"Query: {plan.get('query', '')}\n"
            f"Intent: {plan.get('intent', '')} | Question type: {question_type}\n"
            f"Tickers: {', '.join(plan.get('tickers', []))}\n"
            f"Sectors: {', '.join(plan.get('sectors', []))}\n"
            f"Themes: {', '.join(plan.get('themes', []))}\n"
            f"Time Horizon: {plan.get('time_horizon', 'weeks')}\n"
            f"Benchmark: {benchmark or 'not specified'}\n"
            f"{user_block}"
            f"{priority_block}"
            f"{sub_q_block}"
            f"{comparison_block}"
            f"{theme_block}"
            f"{falsification_block}"
            f"{legacy_requests_block}"
            f"\n\nGather data per the priority ranking, then produce your JSON summary. "
            f"Your data_summary MUST be structured to answer the sub-questions explicitly "
            f"(label them Q1/Q2/...) and cite the comparison_set tickers when discussing valuation."
        )
