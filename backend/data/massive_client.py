"""
Massive market-data client (api.massive.com — Polygon.io-compatible REST API).

This is the single source of market data for Alpha Engine after the
data-layer consolidation. It replaces:
  - Alpha Vantage  (technical indicators / top-movers) — now recomputed from
    Massive OHLCV in the quant layer; movers come from grouped daily aggs.
  - yfinance        (prices / fundamentals / options) — prices come from
    aggregate bars, fundamentals are COMPUTED from the financials endpoint,
    options from the options snapshot.
  - Finnhub + NewsAPI (news) — news comes from the Massive ticker-news feed
    (Firecrawl is the fallback elsewhere in the stack).

Design notes (match the rest of the data layer):
  - Every public function is module-level and SYNCHRONOUS. Agents call these
    from LangChain tool wrappers; async callers wrap them in `run_sync`.
  - Every function is CACHED via a bounded TTLCache to conserve the API quota.
  - Every HTTP call goes through `infra.http.http_get_json` (retries, timeouts,
    Retry-After handling).
  - Auth is a single query param `apiKey=settings.MASSIVE_API_KEY` on every
    request.
  - NOTHING raises. On any failure we log and return the empty shape the
    callers expect: [] / {} / None. A blind data source must never crash a
    desk run.

Adjustment semantics:
  - Aggregate bars from Massive/Polygon adjust for SPLITS only when
    adjusted=True. Total-return (dividend) adjustment is NOT available from
    the aggregates endpoint. `price_bars(..., adjusted=True)` is therefore
    split-adjusted total return; full dividend-adjusted total return is a
    TODO(alpha) — would require the dividends endpoint + manual back-adjust.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from config import settings
from infra.cache import TTLCache
from infra.http import HttpError, http_get_json

logger = logging.getLogger(__name__)

# api.polygon.io is the same API and works with the same key; the Massive
# host is the canonical one for this deployment.
_BASE_URL = "https://api.massive.com"

# ── Cache TTLs (seconds) — mirror the old client budgets ────────────────
_AGG_TTL = 900            # 15 min — intraday bars; agents don't need ticks
_PRICE_TTL = 900          # 15 min — same as old market_client price cache
_QUOTE_TTL = 300          # 5 min  — prev/last close
_REFERENCE_TTL = 86400    # 24 h   — ticker reference details barely change
_FINANCIALS_TTL = 21600   # 6 h    — financials are quarterly; reports immutable
_OPTIONS_TTL = 900        # 15 min — options snapshot shifts intraday
_NEWS_TTL = 1800          # 30 min — matches old NewsAPI budget cadence
_GROUPED_TTL = 3600       # 1 h    — one grouped-daily payload per session
_BETA_TTL = 3600          # 1 h    — derived from 1y of daily bars

# Bounded cache sizes — a screen can touch O(100s) of tickers.
_AGG_MAX = 512
_PRICE_MAX = 512
_QUOTE_MAX = 1024
_REFERENCE_MAX = 1024
_FINANCIALS_MAX = 512
_OPTIONS_MAX = 256
_NEWS_MAX = 512
_GROUPED_MAX = 16
_BETA_MAX = 512

_agg_cache: TTLCache[list] = TTLCache(max_entries=_AGG_MAX, ttl_seconds=_AGG_TTL)
_price_cache: TTLCache[list] = TTLCache(max_entries=_PRICE_MAX, ttl_seconds=_PRICE_TTL)
_quote_cache: TTLCache = TTLCache(max_entries=_QUOTE_MAX, ttl_seconds=_QUOTE_TTL)
_reference_cache: TTLCache[dict] = TTLCache(max_entries=_REFERENCE_MAX, ttl_seconds=_REFERENCE_TTL)
_financials_cache: TTLCache[list] = TTLCache(max_entries=_FINANCIALS_MAX, ttl_seconds=_FINANCIALS_TTL)
_options_cache: TTLCache[dict] = TTLCache(max_entries=_OPTIONS_MAX, ttl_seconds=_OPTIONS_TTL)
_news_cache: TTLCache[list] = TTLCache(max_entries=_NEWS_MAX, ttl_seconds=_NEWS_TTL)
_grouped_cache: TTLCache[list] = TTLCache(max_entries=_GROUPED_MAX, ttl_seconds=_GROUPED_TTL)
_beta_cache: TTLCache = TTLCache(max_entries=_BETA_MAX, ttl_seconds=_BETA_TTL)


# ── Internal helpers ─────────────────────────────────────────────────────

def _get(path: str, *, params: dict | None = None, label: str = "massive"):
    """Single resilient GET against the Massive API.

    Returns decoded JSON (dict/list) on success, or None on any failure.
    Never raises — callers translate None into their empty shape.
    """
    if not settings.MASSIVE_API_KEY:
        logger.debug("MASSIVE_API_KEY not set — skipping %s", path)
        return None

    p = dict(params or {})
    p["apiKey"] = settings.MASSIVE_API_KEY
    url = f"{_BASE_URL}{path}"
    try:
        return http_get_json(
            url,
            params=p,
            read_timeout=20,
            total_timeout=30,
            max_retries=2,
            label=label,
        )
    except HttpError as e:
        logger.warning("Massive fetch failed [%s]: %s", label, e)
        return None
    except Exception as e:  # noqa: BLE001 — a data source must never crash a run
        logger.warning("Massive fetch unexpected error [%s]: %s", label, e)
        return None


def _to_float(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


_PERIOD_DAYS = {
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
    "max": 1825,
}


def _period_to_range(period: str = "6mo") -> tuple[str, str]:
    """Map a yfinance-style period string to (from_date, to_date) as
    YYYY-MM-DD strings.

    Uses runtime `datetime.now()` (acceptable — this is a date window, not a
    network call). "ytd" anchors to Jan 1 of the current year. "max" is
    capped at ~5y back (1825 days) since Massive aggregate history beyond
    that is rarely needed and keeps payloads bounded.
    """
    today = datetime.now()
    to_date = today.strftime("%Y-%m-%d")
    period = (period or "6mo").lower()
    if period == "ytd":
        from_dt = datetime(today.year, 1, 1)
    else:
        days = _PERIOD_DAYS.get(period, 180)
        from_dt = today - timedelta(days=days)
    return from_dt.strftime("%Y-%m-%d"), to_date


# ── Public API ───────────────────────────────────────────────────────────

def agg_bars(
    ticker: str,
    multiplier: int,
    timespan: str,
    from_date: str,
    to_date: str,
    adjusted: bool = True,
    limit: int = 50000,
) -> list:
    """Raw aggregate bars for a ticker over a custom window.

    GET /v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from}/{to}
        ?adjusted=&sort=asc&limit=

    Returns the raw `results` list of bar dicts (keys: t, o, h, l, c, v, vw,
    n) exactly as Massive returns them. Returns [] on failure / no data.
    """
    if not ticker:
        return []
    tk = ticker.upper()
    cache_key = f"{tk}:{multiplier}:{timespan}:{from_date}:{to_date}:{int(bool(adjusted))}:{limit}"
    cached = _agg_cache.get(cache_key)
    if cached is not None:
        return cached

    path = f"/v2/aggs/ticker/{tk}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
    data = _get(
        path,
        params={
            "adjusted": "true" if adjusted else "false",
            "sort": "asc",
            "limit": limit,
        },
        label=f"massive.aggs({tk})",
    )
    if not isinstance(data, dict):
        return []
    results = data.get("results")
    if not isinstance(results, list):
        # Valid response, just no bars (e.g. delisted / bad window).
        results = []
    _agg_cache.set(cache_key, results)
    return results


def price_bars(
    ticker: str,
    period: str = "6mo",
    adjusted: bool = False,
    round_dp: int = 2,
) -> list:
    """OHLCV daily bars in the canonical data-contract shape.

    Returns a list of {date, open, high, low, close, volume} dicts, sorted
    ascending by date. `date` is "YYYY-MM-DD", OHLC are floats rounded to
    `round_dp`, volume is int. This MUST match the old yfinance
    `get_price_history` shape byte-for-byte so downstream quant code (spreads,
    cointegration, factors, backtester) needs zero changes.

    NOTE on adjustment: Massive aggregates adjust SPLITS only. adjusted=True
    therefore yields split-adjusted total return; dividend adjustment is a
    TODO(alpha).
    """
    if not ticker:
        return []
    tk = ticker.upper()
    cache_key = f"{tk}:{period}:{int(bool(adjusted))}:{round_dp}"
    cached = _price_cache.get(cache_key)
    if cached is not None:
        return cached

    from_date, to_date = _period_to_range(period)
    raw = agg_bars(tk, 1, "day", from_date, to_date, adjusted=adjusted, limit=50000)

    out: list[dict] = []
    for bar in raw:
        try:
            t_ms = bar.get("t")
            if t_ms is None:
                continue
            # Polygon timestamps are epoch milliseconds (UTC). Bars are daily,
            # so the date is the bar's UTC date.
            dt = datetime.utcfromtimestamp(t_ms / 1000.0)
            o = _to_float(bar.get("o"))
            h = _to_float(bar.get("h"))
            low = _to_float(bar.get("l"))
            c = _to_float(bar.get("c"))
            v = bar.get("v")
            if None in (o, h, low, c) or v is None:
                continue
            out.append({
                "date": dt.strftime("%Y-%m-%d"),
                "open": round(o, round_dp),
                "high": round(h, round_dp),
                "low": round(low, round_dp),
                "close": round(c, round_dp),
                "volume": int(v),
            })
        except (TypeError, ValueError, OSError) as e:
            logger.debug("price_bars: skipping malformed bar for %s: %s", tk, e)
            continue

    if out:
        _price_cache.set(cache_key, out)
    logger.info("Fetched %d price bars for %s (%s)", len(out), tk, period)
    return out


def prev_close(ticker: str) -> float | None:
    """Previous trading day's close.

    GET /v2/aggs/ticker/{ticker}/prev  -> results[0].c
    Returns the close as a float, or None on failure.
    """
    if not ticker:
        return None
    tk = ticker.upper()
    cache_key = f"PREV:{tk}"
    cached = _quote_cache.get(cache_key)
    if cached is not None:
        return cached

    data = _get(
        f"/v2/aggs/ticker/{tk}/prev",
        params={"adjusted": "true"},
        label=f"massive.prev({tk})",
    )
    close: float | None = None
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list) and results:
            close = _to_float(results[0].get("c"))
    if close is not None:
        _quote_cache.set(cache_key, close)
    return close


def last_price(ticker: str) -> float | None:
    """Best-available current price for a ticker.

    Free/standard plans don't always expose a real-time last trade, so we use
    a fallback chain: previous close (always available) is the reliable
    anchor. This is what populates `current_price` in computed fundamentals.
    Returns None on failure.
    """
    if not ticker:
        return None
    tk = ticker.upper()
    cache_key = f"LAST:{tk}"
    cached = _quote_cache.get(cache_key)
    if cached is not None:
        return cached

    price: float | None = None
    # Primary: snapshot last trade (may be entitlement-gated on some plans).
    snap = _get(
        f"/v2/snapshot/locale/us/markets/stocks/tickers/{tk}",
        label=f"massive.snapshot({tk})",
    )
    if isinstance(snap, dict):
        t = snap.get("ticker") or {}
        last_trade = (t.get("lastTrade") or {}) if isinstance(t, dict) else {}
        price = _to_float(last_trade.get("p"))
        if price is None:
            day = (t.get("day") or {}) if isinstance(t, dict) else {}
            price = _to_float(day.get("c")) or None

    # Fallback: previous close (always available on every plan).
    if price is None or price == 0:
        price = prev_close(tk)

    if price is not None:
        _quote_cache.set(cache_key, price)
    return price


def ticker_reference(ticker: str) -> dict:
    """Reference details for a ticker.

    GET /v3/reference/tickers/{ticker}

    Returns a flat dict the rest of the stack consumes:
        {ticker, name, market_cap, sector, primary_exchange,
         weighted_shares_outstanding, share_class_shares_outstanding,
         sic_code, currency, type, active}
    `sector` is mapped from Massive's `sic_description` (the closest field
    Massive exposes — there is no GICS sector). Returns {} on failure.
    """
    if not ticker:
        return {}
    tk = ticker.upper()
    cached = _reference_cache.get(tk)
    if cached is not None:
        return cached

    data = _get(f"/v3/reference/tickers/{tk}", label=f"massive.reference({tk})")
    if not isinstance(data, dict):
        return {}
    res = data.get("results")
    if not isinstance(res, dict):
        return {}

    out = {
        "ticker": res.get("ticker") or tk,
        "name": res.get("name"),
        "market_cap": _to_float(res.get("market_cap")),
        # Massive has no GICS sector; sic_description is the closest proxy.
        "sector": res.get("sic_description"),
        "sic_description": res.get("sic_description"),
        "sic_code": res.get("sic_code"),
        "primary_exchange": res.get("primary_exchange"),
        "weighted_shares_outstanding": _to_float(res.get("weighted_shares_outstanding")),
        "share_class_shares_outstanding": _to_float(res.get("share_class_shares_outstanding")),
        "currency": res.get("currency_name"),
        "type": res.get("type"),
        "active": res.get("active"),
    }
    _reference_cache.set(tk, out)
    return out


def financials(ticker: str, limit: int = 8) -> list:
    """Raw quarterly financial reports for a ticker.

    GET /vX/reference/financials?ticker=&timeframe=quarterly&limit=&order=desc

    Returns the raw `results` list (each entry has `financials` with
    `income_statement`, `balance_sheet`, `cash_flow_statement`, plus
    `fiscal_period`, `fiscal_year`, `start_date`, `end_date`). The
    fundamentals-computation layer (market_client replacement) consumes these
    raw reports to derive P/E, EV/EBITDA, margins, growth, debt/equity, FCF.
    Returns [] on failure.
    """
    if not ticker:
        return []
    tk = ticker.upper()
    cache_key = f"{tk}:{limit}"
    cached = _financials_cache.get(cache_key)
    if cached is not None:
        return cached

    data = _get(
        "/vX/reference/financials",
        params={
            "ticker": tk,
            "timeframe": "quarterly",
            "limit": limit,
            "order": "desc",
        },
        label=f"massive.financials({tk})",
    )
    if not isinstance(data, dict):
        return []
    results = data.get("results")
    if not isinstance(results, list):
        results = []
    _financials_cache.set(cache_key, results)
    return results


def options_snapshot(ticker: str, expiry: str | None = None) -> dict:
    """Options chain snapshot in the canonical market_client options shape.

    GET /v3/snapshot/options/{ticker}  (paginated; expiration_date filter
    applied when `expiry` is given).

    Returns:
        {
          "expiration": <str|None>,        # the expiry these contracts share,
                                           # or None when mixed/unfiltered
          "all_expirations": [<str>, ...], # up to 5 nearest expiries seen
          "calls": [ {strike, lastPrice, bid, ask, volume, openInterest,
                      impliedVolatility}, ... ],
          "puts":  [ ...same shape... ],
        }
    This matches the yfinance `get_options_chain` contract so the Options Flow
    Agent and options_analytics need zero changes. Returns the empty shape
    {"expirations": [], "calls": [], "puts": []} on failure (same as the old
    client's failure return).
    """
    empty = {"expirations": [], "calls": [], "puts": []}
    if not ticker:
        return empty
    tk = ticker.upper()
    cache_key = f"{tk}:{expiry or 'all'}"
    cached = _options_cache.get(cache_key)
    if cached is not None:
        return cached

    params: dict = {"limit": 250, "order": "asc", "sort": "strike_price"}
    if expiry:
        params["expiration_date"] = expiry
    data = _get(
        f"/v3/snapshot/options/{tk}",
        params=params,
        label=f"massive.options({tk})",
    )
    if not isinstance(data, dict):
        return empty
    results = data.get("results")
    if not isinstance(results, list) or not results:
        return empty

    calls: list[dict] = []
    puts: list[dict] = []
    expirations_seen: list[str] = []

    for contract in results:
        if not isinstance(contract, dict):
            continue
        details = contract.get("details") or {}
        day = contract.get("day") or {}
        greeks_oi = contract  # open_interest / implied_volatility live at top level

        ctype = (details.get("contract_type") or "").lower()
        exp = details.get("expiration_date")
        if exp and exp not in expirations_seen:
            expirations_seen.append(exp)

        row = {
            "strike": _to_float(details.get("strike_price")),
            "lastPrice": _to_float(day.get("close") or day.get("last_price")),
            "bid": _to_float((contract.get("last_quote") or {}).get("bid")),
            "ask": _to_float((contract.get("last_quote") or {}).get("ask")),
            "volume": int(day.get("volume") or 0),
            "openInterest": int(greeks_oi.get("open_interest") or 0),
            "impliedVolatility": _to_float(greeks_oi.get("implied_volatility")),
        }
        if ctype == "call":
            calls.append(row)
        elif ctype == "put":
            puts.append(row)

    # Trim around the money like the old client (keep payloads bounded).
    def _trim(rows: list[dict]) -> list[dict]:
        if len(rows) > 30:
            mid = len(rows) // 2
            return rows[mid - 15: mid + 15]
        return rows

    calls = _trim(calls)
    puts = _trim(puts)

    expirations_seen.sort()
    out = {
        "expiration": expiry or (expirations_seen[0] if expirations_seen else None),
        "all_expirations": expirations_seen[:5],
        "calls": calls,
        "puts": puts,
    }
    _options_cache.set(cache_key, out)
    logger.info("Fetched options snapshot for %s exp=%s", tk, out.get("expiration"))
    return out


def ticker_news(ticker: str, limit: int = 10) -> list:
    """Recent news articles for a ticker.

    GET /v2/reference/news?ticker=&limit=&order=desc

    Returns a list of {title, description, source, published_at, url} dicts —
    the same shape the old NewsAPI client produced so the Sentiment Agent
    needs zero changes. `description` maps from the article's
    description/summary. Returns [] on failure.
    """
    if not ticker:
        return []
    tk = ticker.upper()
    cache_key = f"{tk}:{limit}"
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return cached

    data = _get(
        "/v2/reference/news",
        params={"ticker": tk, "limit": limit, "order": "desc", "sort": "published_utc"},
        label=f"massive.news({tk})",
    )
    if not isinstance(data, dict):
        return []
    results = data.get("results")
    if not isinstance(results, list):
        return []

    out: list[dict] = []
    for art in results:
        if not isinstance(art, dict):
            continue
        publisher = art.get("publisher") or {}
        out.append({
            "title": art.get("title"),
            "description": art.get("description") or art.get("summary"),
            "source": publisher.get("name") if isinstance(publisher, dict) else None,
            "published_at": art.get("published_utc"),
            "url": art.get("article_url") or art.get("amp_url"),
        })
    _news_cache.set(cache_key, out)
    return out


def grouped_daily(date_str: str) -> list:
    """All US stock daily bars for a single date (the screener's universe).

    GET /v2/aggs/grouped/locale/us/market/stocks/{date}?adjusted=true

    Returns the raw `results` list of per-ticker daily bars (keys: T (ticker),
    o, h, l, c, v, vw, n). Returns [] on failure or for a non-trading day.
    `date_str` is "YYYY-MM-DD".
    """
    if not date_str:
        return []
    cached = _grouped_cache.get(date_str)
    if cached is not None:
        return cached

    data = _get(
        f"/v2/aggs/grouped/locale/us/market/stocks/{date_str}",
        params={"adjusted": "true"},
        label=f"massive.grouped({date_str})",
    )
    if not isinstance(data, dict):
        return []
    results = data.get("results")
    if not isinstance(results, list):
        results = []
    _grouped_cache.set(date_str, results)
    return results


def compute_beta(ticker: str, benchmark: str = "SPY", period: str = "1y") -> float | None:
    """Beta of `ticker` vs `benchmark` from daily returns.

    beta = cov(r_ticker, r_bench) / var(r_bench), computed on overlapping
    daily simple returns over `period`. Returns None when there's
    insufficient overlapping data (< 2 return observations) or var(bench)==0.
    """
    if not ticker:
        return None
    tk = ticker.upper()
    bm = (benchmark or "SPY").upper()
    cache_key = f"{tk}:{bm}:{period}"
    cached = _beta_cache.get(cache_key)
    if cached is not None:
        return cached

    tk_bars = price_bars(tk, period=period, adjusted=True)
    bm_bars = price_bars(bm, period=period, adjusted=True)
    if not tk_bars or not bm_bars:
        return None

    tk_close = {b["date"]: b["close"] for b in tk_bars}
    bm_close = {b["date"]: b["close"] for b in bm_bars}
    common_dates = sorted(set(tk_close) & set(bm_close))
    if len(common_dates) < 3:
        return None

    tk_rets: list[float] = []
    bm_rets: list[float] = []
    for i in range(1, len(common_dates)):
        d0, d1 = common_dates[i - 1], common_dates[i]
        p0t, p1t = tk_close[d0], tk_close[d1]
        p0b, p1b = bm_close[d0], bm_close[d1]
        if p0t and p0b:
            tk_rets.append(p1t / p0t - 1.0)
            bm_rets.append(p1b / p0b - 1.0)

    n = len(bm_rets)
    if n < 2:
        return None

    mean_t = sum(tk_rets) / n
    mean_b = sum(bm_rets) / n
    cov = sum((tk_rets[i] - mean_t) * (bm_rets[i] - mean_b) for i in range(n)) / n
    var_b = sum((bm_rets[i] - mean_b) ** 2 for i in range(n)) / n
    if var_b == 0:
        return None

    beta = round(cov / var_b, 4)
    _beta_cache.set(cache_key, beta)
    return beta
