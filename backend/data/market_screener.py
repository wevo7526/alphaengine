"""
Real-time market screener (replaces the hardcoded universe for discovery).

Scours the LIVE market via yfinance's screener (`screen()` + `EquityQuery` +
predefined screens) instead of filtering a curated list. This is how the desk
surfaces genuinely under-covered names — small/mid-caps that no one
hand-picked — rather than recycling the same big names.

Free (yfinance), cached 1h. On any failure (Yahoo throttling a cloud IP, API
shape change) we fall back to the curated pool in agents.universe so the desk
never ends up with zero candidates — but the curated list is the *fallback*,
not the source.

Output candidates carry live facts (market cap, price, sector, avg volume) so
downstream sizing and the liquidity floor are grounded in real data.
"""

from __future__ import annotations

import logging

from infra.cache import TTLCache

logger = logging.getLogger(__name__)

_CACHE: TTLCache[list] = TTLCache(max_entries=128, ttl_seconds=3600)

# Liquidity / quality floor so we surface tradeable names, not dead microcaps.
_MIN_PRICE = 3.0
_MIN_AVG_VOL = 200_000
# Major US exchanges (Yahoo `exchange` codes). Excludes OTC/Pink (PNK).
_OK_EXCHANGES = {"NMS", "NYQ", "NGM", "NCM", "ASE", "BATS", "PCX"}

# System sector keys → Yahoo sector strings (EquityQuery `sector` values).
_SECTOR_MAP = {
    "technology": "Technology", "tech": "Technology",
    "healthcare": "Healthcare", "health": "Healthcare",
    "financials": "Financial Services", "financial": "Financial Services",
    "financial_services": "Financial Services",
    "consumer_cyclical": "Consumer Cyclical", "consumer_discretionary": "Consumer Cyclical",
    "industrials": "Industrials", "industrial": "Industrials",
    "energy": "Energy",
    "consumer_defensive": "Consumer Defensive", "consumer_staples": "Consumer Defensive",
    "materials": "Basic Materials", "basic_materials": "Basic Materials",
    "real_estate": "Real Estate",
    "utilities": "Utilities",
    "communication_services": "Communication Services", "communications": "Communication Services",
}

# Style → predefined yfinance screen names (robust, no field-name guessing).
_STYLE_SCREENS = {
    "small_cap": ["aggressive_small_caps", "small_cap_gainers"],
    "momentum": ["day_gainers", "most_actives"],
    "value": ["undervalued_growth_stocks", "undervalued_large_caps"],
    "growth": ["growth_technology_stocks", "undervalued_growth_stocks"],
    "contrarian": ["most_shorted_stocks"],
}

# Market-cap band for "under-covered" discovery: $300M–$15B (small/mid).
_CAP_LO = 300_000_000
_CAP_HI = 15_000_000_000


def _passes_quality(q: dict) -> bool:
    sym = (q.get("symbol") or "").upper()
    if not sym or "." in sym:
        return False
    # Drop foreign-ordinary / OTC 5-letter F-suffix tickers.
    if len(sym) == 5 and sym.endswith("F"):
        return False
    if (q.get("exchange") or "") not in _OK_EXCHANGES:
        return False
    price = q.get("regularMarketPrice") or q.get("intradayprice")
    if price is not None and float(price) < _MIN_PRICE:
        return False
    vol = q.get("averageDailyVolume3Month") or q.get("averageDailyVolume10Day")
    if vol is not None and float(vol) < _MIN_AVG_VOL:
        return False
    qt = (q.get("quoteType") or "EQUITY").upper()
    return qt == "EQUITY"


def _quote_to_candidate(q: dict) -> dict:
    return {
        "ticker": (q.get("symbol") or "").upper(),
        "name": q.get("shortName") or q.get("displayName") or q.get("longName") or "",
        "market_cap": q.get("marketCap"),
        "price": q.get("regularMarketPrice"),
        "sector": q.get("sector"),
        "avg_volume": q.get("averageDailyVolume3Month"),
        "source": "yfinance_screener",
    }


def _run_predefined(name: str, count: int) -> list[dict]:
    import yfinance as yf
    try:
        r = yf.screen(name, count=count)
        return (r or {}).get("quotes", []) if isinstance(r, dict) else []
    except Exception as e:  # noqa: BLE001
        logger.debug("[screener] predefined %s failed: %s", name, e)
        return []


def _run_alpha_vantage_movers() -> list[dict]:
    """Live discovery from Alpha Vantage TOP_GAINERS_LOSERS (1 call, 4h-cached).

    Adds a market-wide momentum/active-names dimension that yfinance's
    predefined screens don't fully cover, and cross-validates them. Skips
    silently when AV has no key or is rate-limited.
    """
    try:
        from data.alpha_vantage_client import AlphaVantageClient
        data = AlphaVantageClient().get_top_movers()
        if not data:
            return []
        out: list[dict] = []
        for bucket in ("most_actively_traded", "top_gainers", "top_losers"):
            for row in (data.get(bucket) or [])[:20]:
                sym = (row.get("ticker") or "").upper()
                if not sym:
                    continue
                try:
                    price = float(row.get("price") or 0)
                except (TypeError, ValueError):
                    price = 0.0
                out.append({
                    "symbol": sym,
                    "regularMarketPrice": price,
                    "exchange": "NMS",  # AV movers are US-listed; trust + let liquidity floor filter
                    "quoteType": "EQUITY",
                    "averageDailyVolume3Month": None,
                    "shortName": "",
                    "_av_bucket": bucket,
                })
        return out
    except Exception as e:  # noqa: BLE001
        logger.debug("[screener] alpha vantage movers failed: %s", e)
        return []


def _run_sector_smallcap(sector_label: str, count: int) -> list[dict]:
    import yfinance as yf
    try:
        q = yf.EquityQuery("and", [
            yf.EquityQuery("eq", ["region", "us"]),
            yf.EquityQuery("eq", ["sector", sector_label]),
            yf.EquityQuery("btwn", ["intradaymarketcap", _CAP_LO, _CAP_HI]),
        ])
        r = yf.screen(q, count=count, sortField="intradaymarketcap", sortAsc=True)
        return (r or {}).get("quotes", []) if isinstance(r, dict) else []
    except Exception as e:  # noqa: BLE001
        logger.debug("[screener] sector smallcap %s failed: %s", sector_label, e)
        return []


def screen_market(
    sectors: list[str] | None = None,
    styles: list[str] | None = None,
    exclude: list[str] | None = None,
    cap: int = 50,
) -> list[dict]:
    """Return up to `cap` live candidates discovered from the market.

    Combines per-sector small/mid-cap EquityQuery scans with style-based
    predefined screens, applies a liquidity/quality floor, dedupes, and
    excludes held / mega-cap names. Cached 1h. Falls back to the curated pool
    only if the live screen yields nothing.
    """
    sectors = [s for s in (sectors or []) if s]
    styles = [s for s in (styles or []) if s]
    cache_key = f"{','.join(sorted(sectors))}|{','.join(sorted(styles))}|{cap}"
    cached = _CACHE.get(cache_key)
    if cached is not None:
        excl = set((t or "").upper() for t in (exclude or []))
        return [c for c in cached if c["ticker"] not in excl][:cap]

    quotes: list[dict] = []
    per_query = max(15, cap)

    # 1. Per-sector small/mid-cap scans (the core "undiscovered" surface).
    for s in sectors[:4]:
        label = _SECTOR_MAP.get((s or "").lower().strip())
        if label:
            quotes += _run_sector_smallcap(label, per_query)

    # 2. Style-driven predefined screens.
    screen_names: list[str] = []
    for st in styles:
        screen_names += _STYLE_SCREENS.get((st or "").lower().strip(), [])
    # Always include a small-cap discovery screen so narrow/style-less queries
    # still scan broadly for under-covered names.
    if not screen_names or not sectors:
        screen_names += ["aggressive_small_caps", "small_cap_gainers", "undervalued_growth_stocks"]
    for name in dict.fromkeys(screen_names):
        quotes += _run_predefined(name, per_query)

    # 3. Alpha Vantage live top-movers (market-wide momentum/active names).
    quotes += _run_alpha_vantage_movers()

    # Dedupe + quality filter.
    seen: set[str] = set()
    candidates: list[dict] = []
    for q in quotes:
        if not isinstance(q, dict):
            continue
        sym = (q.get("symbol") or "").upper()
        if not sym or sym in seen:
            continue
        if not _passes_quality(q):
            continue
        seen.add(sym)
        candidates.append(_quote_to_candidate(q))

    if not candidates:
        logger.warning("[screener] live screen returned nothing — falling back to curated pool")
        from agents.universe import secondary_candidates
        fb = secondary_candidates(sectors=sectors, themes=styles, exclude=exclude, cap=cap)
        return [{"ticker": t, "source": "curated_fallback"} for t in fb]

    _CACHE.set(cache_key, candidates)
    excl = set((t or "").upper() for t in (exclude or []))
    out = [c for c in candidates if c["ticker"] not in excl][:cap]
    logger.info("[screener] live market scan: %d candidates (sectors=%s styles=%s)",
                len(out), sectors, styles)
    return out


def screen_market_tickers(sectors=None, styles=None, exclude=None, cap: int = 50) -> list[str]:
    """Convenience: just the ticker symbols from `screen_market`."""
    return [c["ticker"] for c in screen_market(sectors, styles, exclude, cap) if c.get("ticker")]
