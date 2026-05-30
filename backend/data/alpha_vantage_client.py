"""
Alpha Vantage — FREE-tier client, narrowly scoped.

Massive provides everything EXCEPT analyst data (price targets, ratings) — it
has no analyst endpoint at any tier. Alpha Vantage's `OVERVIEW` endpoint
returns analyst target price + a rating distribution + ready fundamentals
(P/E, EV/EBITDA, beta, 52-week range, EPS) in ONE call. That single gap is
the only thing we spend the scarce free quota on.

Free-tier discipline:
  - 25 requests/day, 5/min. A process-wide per-DAY budget guard
    (ALPHA_VANTAGE_DAILY_BUDGET, default 20) stops us before the hard cap;
    over budget we return {} and the caller degrades (nulls).
  - 24h cache: OVERVIEW barely changes intraday, so one call per name per day
    is plenty.
  - AV signals quota/errors in the JSON body ("Note"/"Information"), not the
    HTTP status — we detect and back off.
  - NOTHING raises. Missing key / over budget / error -> {}.
"""

from __future__ import annotations

import logging
import threading
from datetime import date

from config import settings
from infra.cache import TTLCache
from infra.http import HttpError, http_get_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"
_OVERVIEW_TTL = 86400  # 24h — analyst data barely moves day to day

_overview_cache: TTLCache[dict] = TTLCache(max_entries=512, ttl_seconds=_OVERVIEW_TTL)

# Per-day budget guard (process-wide).
_budget_lock = threading.Lock()
_calls_today = 0
_calls_date: str | None = None


def _budget_take() -> bool:
    """Reserve one call against today's budget. Returns False if exhausted."""
    global _calls_today, _calls_date
    budget = int(getattr(settings, "ALPHA_VANTAGE_DAILY_BUDGET", 20))
    with _budget_lock:
        today = date.today().isoformat()
        if _calls_date != today:
            _calls_date = today
            _calls_today = 0
        if _calls_today >= budget:
            return False
        _calls_today += 1
        return True


def _f(v) -> float | None:
    """AV returns strings, and 'None'/'-' for missing values."""
    if v in (None, "None", "-", "", "0", "0.0"):
        # 0 is almost always a missing-value sentinel for these fields.
        return None
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def get_overview(ticker: str) -> dict:
    """Analyst + fundamentals snapshot from AV OVERVIEW. {} when unavailable.

    Returns a normalized dict:
        {analyst_target_price, recommendation_key, num_analysts,
         pe_ratio, forward_pe, ev_ebitda, beta, eps, peg,
         profit_margin, dividend_yield, market_cap,
         "52w_high", "52w_low", sector, industry, revenue_growth}
    """
    if not ticker:
        return {}
    tk = ticker.upper()
    cached = _overview_cache.get(tk)
    if cached is not None:
        return cached

    if not settings.ALPHA_VANTAGE_KEY:
        return {}
    if not _budget_take():
        logger.info("Alpha Vantage daily budget spent — skipping OVERVIEW(%s)", tk)
        return {}

    try:
        data = http_get_json(
            _BASE_URL,
            params={"function": "OVERVIEW", "symbol": tk, "apikey": settings.ALPHA_VANTAGE_KEY},
            read_timeout=15,
            total_timeout=20,
            max_retries=1,
            label=f"alphavantage.overview({tk})",
        )
    except HttpError as e:
        logger.warning("Alpha Vantage OVERVIEW failed for %s: %s", tk, e)
        return {}

    if not isinstance(data, dict) or not data or "Symbol" not in data:
        # Empty {} or a quota note ("Note"/"Information") -> nothing usable.
        msg = (data or {}).get("Note") or (data or {}).get("Information") if isinstance(data, dict) else None
        if msg:
            logger.warning("Alpha Vantage rate/quota note for %s: %s", tk, msg)
        return {}

    # Map AV's rating distribution to a single recommendation_key.
    sb = _f(data.get("AnalystRatingStrongBuy")) or 0
    b = _f(data.get("AnalystRatingBuy")) or 0
    h = _f(data.get("AnalystRatingHold")) or 0
    s = _f(data.get("AnalystRatingSell")) or 0
    ss = _f(data.get("AnalystRatingStrongSell")) or 0
    total = sb + b + h + s + ss
    rec = None
    if total > 0:
        score = (sb * 2 + b * 1 - s * 1 - ss * 2) / total
        rec = ("strong_buy" if score >= 1.0 else "buy" if score >= 0.25
               else "hold" if score > -0.25 else "sell" if score > -1.0 else "strong_sell")

    out = {
        "analyst_target_price": _f(data.get("AnalystTargetPrice")),
        "recommendation_key": rec,
        "num_analysts": int(total) if total else None,
        "pe_ratio": _f(data.get("PERatio")),
        "forward_pe": _f(data.get("ForwardPE")),
        "ev_ebitda": _f(data.get("EVToEBITDA")),
        "beta": _f(data.get("Beta")),
        "eps": _f(data.get("EPS")),
        "peg": _f(data.get("PEGRatio")),
        "profit_margin": _f(data.get("ProfitMargin")),
        "dividend_yield": _f(data.get("DividendYield")),
        "market_cap": _f(data.get("MarketCapitalization")),
        "52w_high": _f(data.get("52WeekHigh")),
        "52w_low": _f(data.get("52WeekLow")),
        "sector": (data.get("Sector") or None),
        "industry": (data.get("Industry") or None),
        "revenue_growth": _f(data.get("QuarterlyRevenueGrowthYOY")),
    }
    _overview_cache.set(tk, out)
    logger.info("Alpha Vantage OVERVIEW for %s (target=%s, rec=%s)", tk, out["analyst_target_price"], rec)
    return out
