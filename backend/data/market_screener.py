"""
Real-time market screener (replaces the hardcoded universe for discovery).

Scours the LIVE market via Massive's grouped-daily aggregates — every US
stock's daily bar for the most recent trading day — joined with Massive
ticker-reference details for sector + market cap. This is how the desk
surfaces genuinely under-covered names — small/mid-caps that no one
hand-picked — rather than recycling the same big names.

Why grouped-daily instead of a screener endpoint: Massive (Polygon-compatible)
has no server-side equity-query screener. The grouped-daily aggregate returns
the whole US tape in a single call, which we filter CLIENT-SIDE for the
small/mid-cap + liquidity criteria the old code used. The single grouped call
is cached 1h; reference lookups (for market cap + sector) only happen for the
liquidity-surviving subset and are themselves cached 24h, so a warm session is
nearly free.

On any failure (no key, non-trading day, API shape change) we fall back to the
curated pool in agents.universe so the desk never ends up with zero
candidates — but the curated list is the *fallback*, not the source.

Output candidates carry live facts (market cap, price, sector, avg volume) so
downstream sizing and the liquidity floor are grounded in real data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from data import massive_client
from infra.cache import TTLCache

logger = logging.getLogger(__name__)

_CACHE: TTLCache[list] = TTLCache(max_entries=128, ttl_seconds=3600)

# Liquidity / quality floor so we surface tradeable names, not dead microcaps.
_MIN_PRICE = 3.0
_MIN_AVG_VOL = 200_000

# Major US exchanges (Massive `primary_exchange` MIC-style codes). Excludes
# OTC/Pink markets. Massive uses ISO-MIC-like codes (XNYS/XNAS/...) as well as
# the legacy Yahoo-style codes for some records, so accept both vocabularies.
_OK_EXCHANGES = {
    # Massive / Polygon MIC codes
    "XNYS", "XNAS", "XASE", "ARCX", "BATS", "IEXG", "XNGS", "XNMS", "XNCM",
    # Legacy Yahoo-style codes (kept so _passes_quality stays back-compatible)
    "NMS", "NYQ", "NGM", "NCM", "ASE", "PCX",
}

# System sector keys → GICS Level-1 sector strings used across the stack.
# (resolve_sector / sector_map speak GICS; Massive only gives an SIC proxy,
# so the join below normalizes Massive's sic_description through that map.)
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

# Market-cap band for "under-covered" discovery: $300M–$15B (small/mid).
_CAP_LO = 300_000_000
_CAP_HI = 15_000_000_000

# How many liquidity-surviving tickers we'll resolve reference details for.
# Each reference lookup is one cached API call; cap the fan-out so a single
# screen can't stampede the quota. Survivors are sorted by dollar-volume
# (liquidity) first, so the cap keeps the most tradeable names.
_MAX_REFERENCE_LOOKUPS = 400


def _passes_quality(q: dict) -> bool:
    """Quality / liquidity floor for a single quote-shaped dict.

    Kept signature-compatible with the old yfinance-era contract (the keys
    `symbol`, `exchange`, `regularMarketPrice`/`intradayprice`,
    `averageDailyVolume3Month`/`averageDailyVolume10Day`, `quoteType`) so the
    existing unit tests and any external callers keep working. The Massive
    join below builds these same keys before calling this.
    """
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
    """Map a quote-shaped dict to the public candidate contract.

    Output shape is unchanged from the yfinance era so downstream consumers
    (blend_discovery_universe, sizing, the liquidity floor) need zero changes:
        {ticker, name, market_cap, price, sector, avg_volume, source}
    `source` is "massive_screener" — the live market screen now runs on Massive
    grouped daily aggregates (yfinance is fully removed).
    """
    return {
        "ticker": (q.get("symbol") or "").upper(),
        "name": q.get("shortName") or q.get("displayName") or q.get("longName") or "",
        "market_cap": q.get("marketCap"),
        "price": q.get("regularMarketPrice"),
        "sector": q.get("sector"),
        "avg_volume": q.get("averageDailyVolume3Month"),
        "source": "massive_screener",
    }


def _most_recent_trading_day() -> str:
    """Best-guess most-recent completed trading day as YYYY-MM-DD.

    Grouped-daily returns [] for weekends/holidays; the caller walks back day
    by day until it gets bars, so this just needs a sensible starting anchor:
    yesterday (today's grouped bar isn't final until after close). Weekends
    are skipped here to save a wasted call or two.
    """
    d = datetime.now() - timedelta(days=1)
    # Sat=5, Sun=6 → step back to Friday.
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _fetch_grouped_universe(max_lookback: int = 5) -> list[dict]:
    """Grouped-daily bars for the most recent trading day with data.

    Walks back up to `max_lookback` days from the anchor so a holiday or a
    stale "yesterday" doesn't yield an empty universe. Returns the raw
    per-ticker bar list (keys: T, o, h, l, c, v, vw, n) or [] if nothing.
    """
    d = datetime.strptime(_most_recent_trading_day(), "%Y-%m-%d")
    for _ in range(max_lookback):
        date_str = d.strftime("%Y-%m-%d")
        bars = massive_client.grouped_daily(date_str)
        if bars:
            logger.info("[screener] grouped universe: %d bars on %s", len(bars), date_str)
            return bars
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return []


def _bar_to_quote(bar: dict, ref: dict | None) -> dict:
    """Build a yfinance-quote-shaped dict from a grouped bar + reference row.

    The grouped bar gives ticker/price/volume; the reference row (when
    available) supplies name, market cap, sector, and exchange. Keys mirror
    the old yfinance screener payload so `_passes_quality` /
    `_quote_to_candidate` consume them unchanged.
    """
    ref = ref or {}
    raw_sector = ref.get("sector")
    return {
        "symbol": (bar.get("T") or "").upper(),
        "regularMarketPrice": massive_client._to_float(bar.get("c")),
        # Single-day share volume is the liquidity proxy here (grouped-daily has
        # no trailing average); the floor in _passes_quality is intentionally
        # the same 200k threshold the old 3-month-average path used.
        "averageDailyVolume3Month": int(bar.get("v") or 0) if bar.get("v") is not None else None,
        "marketCap": ref.get("market_cap"),
        "sector": _normalize_sector(raw_sector, (bar.get("T") or "").upper()),
        "shortName": ref.get("name") or "",
        "exchange": ref.get("primary_exchange") or "",
        # Massive reference `type` is "CS"/"ETF"/... — map to the yfinance
        # quoteType vocabulary _passes_quality expects.
        "quoteType": _normalize_quote_type(ref.get("type")),
    }


def _normalize_quote_type(massive_type: str | None) -> str:
    """Map a Massive reference security `type` to a yfinance quoteType.

    "CS"/"ADRC" (common stock / ADR) → EQUITY; "ETF"/"ETN"/"FUND" → ETF.
    Unknown/absent defaults to EQUITY so a missing reference row doesn't
    silently drop a genuine equity (the liquidity floor still gates it).
    """
    t = (massive_type or "").upper()
    if t in {"ETF", "ETN", "ETV", "FUND", "ETS"}:
        return "ETF"
    return "EQUITY"


def _normalize_sector(massive_sic_description: str | None, ticker: str) -> str | None:
    """Resolve a GICS-style sector for the candidate.

    Massive only exposes `sic_description` (an SIC proxy), not GICS. We prefer
    the hardcoded GICS map (resolve_sector) when the ticker is known there;
    otherwise we pass through Massive's sic_description so the field is at
    least populated. Returns None only when nothing is available.
    """
    try:
        from data.sector_map import resolve_sector
        sector, src = resolve_sector(ticker)
        if src != "unresolved":
            return sector
    except Exception:  # noqa: BLE001 — sector resolution must never break a screen
        pass
    return massive_sic_description or None


def _matches_requested_sectors(candidate_sector: str | None, sectors: list[str]) -> bool:
    """True if `candidate_sector` matches any requested system-sector key.

    Empty `sectors` means "no sector filter" → always True.
    """
    if not sectors:
        return True
    if not candidate_sector:
        return False
    wanted = {
        _SECTOR_MAP.get((s or "").lower().strip())
        for s in sectors
    }
    wanted.discard(None)
    return candidate_sector in wanted


def screen_market(
    sectors: list[str] | None = None,
    styles: list[str] | None = None,
    exclude: list[str] | None = None,
    cap: int = 50,
) -> list[dict]:
    """Return up to `cap` live candidates discovered from the market.

    Pulls the full US tape via Massive grouped-daily, filters client-side for
    the price/liquidity floor, ranks by dollar-volume, resolves reference
    details (market cap + sector) for the survivors, applies the small/mid-cap
    band and any requested sector filter, dedupes, and excludes held names.
    Cached 1h. Falls back to the curated pool only if the live screen yields
    nothing.

    NOTE: `styles` is accepted for signature/contract compatibility. Massive
    has no predefined style screens (day_gainers, undervalued_growth, ...);
    discovery is liquidity- and cap-driven from the grouped tape instead. The
    parameter is retained so callers and the cache key are unchanged.
    """
    sectors = [s for s in (sectors or []) if s]
    styles = [s for s in (styles or []) if s]
    cache_key = f"{','.join(sorted(sectors))}|{','.join(sorted(styles))}|{cap}"
    cached = _CACHE.get(cache_key)
    if cached is not None:
        excl = set((t or "").upper() for t in (exclude or []))
        return [c for c in cached if c["ticker"] not in excl][:cap]

    try:
        candidates = _discover(sectors, styles, cap)
    except Exception as e:  # noqa: BLE001 — never let a screen crash a desk run
        logger.exception("[screener] live screen errored: %s", e)
        candidates = []

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


def _discover(sectors: list[str], styles: list[str], cap: int) -> list[dict]:
    """Core discovery: grouped tape → liquidity floor → reference join → band.

    Returns the deduped candidate list (pre-exclude, pre-cap-slice) or [] when
    the grouped universe is unavailable. Kept separate from `screen_market` so
    caching/exclude/fallback logic stays readable and the heavy path is wrapped
    in a single try at the call site.
    """
    bars = _fetch_grouped_universe()
    if not bars:
        return []

    # 1. First pass: cheap price/volume floor on the raw tape (no API calls).
    #    Rank survivors by dollar-volume so the bounded reference fan-out spends
    #    its budget on the most liquid names.
    prelim: list[tuple[float, dict]] = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        sym = (bar.get("T") or "").upper()
        if not sym or "." in sym:
            continue
        price = massive_client._to_float(bar.get("c"))
        vol = bar.get("v")
        if price is None or price < _MIN_PRICE:
            continue
        if vol is None or float(vol) < _MIN_AVG_VOL:
            continue
        dollar_vol = price * float(vol)
        prelim.append((dollar_vol, bar))

    prelim.sort(key=lambda x: x[0], reverse=True)
    prelim = prelim[:_MAX_REFERENCE_LOOKUPS]

    # 2. Resolve reference details (market cap + sector + exchange + type) for
    #    the survivors, build quote-shaped dicts, apply the full quality floor,
    #    the small/mid-cap band, and the requested-sector filter. Dedupe.
    seen: set[str] = set()
    candidates: list[dict] = []
    for _dollar_vol, bar in prelim:
        sym = (bar.get("T") or "").upper()
        if sym in seen:
            continue
        ref = massive_client.ticker_reference(sym)
        q = _bar_to_quote(bar, ref)

        if not _passes_quality(q):
            continue

        # Small/mid-cap discovery band. When market cap is unknown (no
        # reference row) we KEEP the name — the liquidity floor already gated
        # it and dropping every cap-less name would silently shrink discovery.
        mcap = q.get("marketCap")
        if mcap is not None and not (_CAP_LO <= float(mcap) <= _CAP_HI):
            continue

        if not _matches_requested_sectors(q.get("sector"), sectors):
            continue

        seen.add(sym)
        candidates.append(_quote_to_candidate(q))
        if len(candidates) >= max(cap * 3, cap + 25):
            # Enough headroom for exclude/cap slicing without resolving the
            # entire survivor list — saves reference calls on big screens.
            break

    return candidates


def screen_market_tickers(sectors=None, styles=None, exclude=None, cap: int = 50) -> list[str]:
    """Convenience: just the ticker symbols from `screen_market`."""
    return [c["ticker"] for c in screen_market(sectors, styles, exclude, cap) if c.get("ticker")]
