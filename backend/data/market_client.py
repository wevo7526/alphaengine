"""
Market data client — Massive-backed (api.massive.com, Polygon.io-compatible).

This is a THIN delegation layer over `data.massive_client`. It preserves the
exact public contract the rest of Alpha Engine depends on (class name,
method names + signatures, async `a*` variants, and — critically — the exact
RETURN SHAPES) so downstream quant code (cointegration, factors, spreads,
backtester, optimizer, pairs, stress, curve) and the agents need ZERO changes.

History: this used to wrap yfinance directly. After the data-layer
consolidation, all market data comes from Massive:
  - Prices            -> massive.price_bars (aggregate bars)
  - Fundamentals      -> COMPUTED from massive.financials + ticker_reference +
                         last_price + 1y price_bars (52w hi/lo) + compute_beta
  - Options           -> massive.options_snapshot
  - Consensus         -> REDUCED: Massive has no analyst data (see method)
  - Earnings calendar -> REDUCED: Massive has no analyst estimates (see method)

Stability notes:
  - `massive_client` functions NEVER raise — they log and return the empty
    shape ([] / {} / None). This client mirrors that: it never crashes a run.
  - The TTLCaches + cache keys are preserved from the old client so cache
    behavior (and any external assumptions about it) is unchanged.
  - Sync methods are still used inside LangChain tool wrappers; async callers
    use the `a*` variants which dispatch onto a thread via `run_sync`.
"""

from __future__ import annotations

import logging

from data import massive_client
from infra.async_utils import run_sync
from infra.cache import TTLCache

logger = logging.getLogger(__name__)

# Cache TTL in seconds (unchanged from the yfinance-era client)
_PRICE_TTL = 900          # 15 min — prices move, but agents don't need tick-level
_FUNDAMENTALS_TTL = 3600  # 1 hour — fundamentals update at most daily
_OPTIONS_TTL = 900        # 15 min — options chains shift intraday

# Bounded sizes: a single user can touch O(100) tickers × periods in a scan.
# 512 entries per cache × ~5 KB each = <3 MB ceiling.
_PRICE_MAX = 512
_FUNDAMENTALS_MAX = 512
_OPTIONS_MAX = 256


def _safe_float(v) -> float | None:
    """Coerce a scalar to a plain float. NaN -> None."""
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _g(d, *keys):
    """Return the first present-and-non-None value among `keys` in dict `d`.

    Massive/Polygon financial statement line items vary by company and
    timeframe; line items are nested as {"value": <num>, ...}. This walks the
    candidate keys and unwraps the `value` field defensively. Returns None if
    nothing matches.
    """
    if not isinstance(d, dict):
        return None
    for k in keys:
        item = d.get(k)
        if item is None:
            continue
        if isinstance(item, dict):
            val = item.get("value")
            if val is not None:
                return val
        else:
            return item
    return None


class MarketDataClient:
    def __init__(self):
        self._price_cache: TTLCache[list[dict]] = TTLCache(
            max_entries=_PRICE_MAX, ttl_seconds=_PRICE_TTL,
        )
        self._fundamentals_cache: TTLCache[dict] = TTLCache(
            max_entries=_FUNDAMENTALS_MAX, ttl_seconds=_FUNDAMENTALS_TTL,
        )
        self._options_cache: TTLCache[dict] = TTLCache(
            max_entries=_OPTIONS_MAX, ttl_seconds=_OPTIONS_TTL,
        )

    # ── Sync interface ─────────────────────────────────────────────
    # Agents still call these inside LangChain tool wrappers (sync).
    # Inside async handlers / agents, prefer the `a*` variants below.

    def get_earnings_calendar(self, ticker: str) -> dict:
        """
        Next earnings date + last reported date for a ticker.

        REDUCED SOURCE: Massive has NO analyst earnings estimates and no
        forward earnings calendar. The yfinance-era version returned
        next_earnings_date / recent_earnings / last_reported populated from
        Yahoo's analyst feed; Massive cannot supply any of those.

        We preserve the return SHAPE (so callers don't break) but populate the
        analyst-only fields with None/empty. Return shape:
            {ticker, next_earnings_date, recent_earnings, last_reported}
        """
        cache_key = f"EARN:{ticker}"
        cached = self._fundamentals_cache.get(cache_key)
        if cached is not None:
            return cached

        # GAP: no Massive source for forward earnings dates or EPS
        # actual/estimate history. Shape preserved, fields nulled.
        result = {
            "ticker": ticker.upper(),
            "next_earnings_date": None,
            "recent_earnings": [],
            "last_reported": None,
        }
        self._fundamentals_cache.set(cache_key, result)
        return result

    def get_consensus(self, ticker: str) -> dict:
        """
        Analyst consensus (target price, recommendation, EPS forward).

        REDUCED SOURCE: Massive has NO analyst data (no price targets, no
        recommendation distribution, no analyst count, no forward EPS). The
        yfinance-era version pulled all of this from Yahoo's `info` block.

        We preserve the return SHAPE and populate only what Massive CAN give:
        `current_price` (from massive.last_price) and `revenue_growth`
        (cheaply derived from the latest two financials reports). All
        analyst-only fields are left None.
        """
        cache_key = f"CONS:{ticker}"
        cached = self._fundamentals_cache.get(cache_key)
        if cached is not None:
            return cached

        current = _safe_float(massive_client.last_price(ticker))

        # revenue_growth is the one consensus field with a Massive source.
        revenue_growth = None
        try:
            reports = massive_client.financials(ticker, limit=8)
            revenue_growth = self._latest_revenue_growth(reports)
        except Exception as e:  # never let the data layer crash a run
            logger.warning("consensus revenue_growth compute failed for %s: %s", ticker, e)

        # GAP: target_*, num_analysts, recommendation_*, *_eps,
        # earnings_growth, implied_upside_pct have NO Massive source -> None.
        result = {
            "ticker": ticker.upper(),
            "current_price": current,
            "target_mean": None,
            "target_high": None,
            "target_low": None,
            "target_median": None,
            "num_analysts": None,
            "recommendation_mean": None,
            "recommendation_key": None,
            "forward_eps": None,
            "trailing_eps": None,
            "earnings_growth": None,
            "revenue_growth": revenue_growth,
            "implied_upside_pct": None,
        }
        self._fundamentals_cache.set(cache_key, result)
        return result

    def get_total_return_history(self, ticker: str, period: str = "1y") -> list[dict]:
        """
        Total-return-adjusted price history (split-adjusted via Massive).

        Adjusted bars at 4dp — used by the backtester. Cached separately from
        `get_price_history` (which keeps unadjusted closes for live UI /
        mark-to-market display).

        NOTE on adjustment: Massive aggregates adjust SPLITS only; full
        dividend adjustment is a TODO(alpha) in massive_client. Shape is
        preserved byte-for-byte from the yfinance era (4dp OHLC, int volume).
        """
        cache_key = f"TR:{ticker}:{period}"
        cached = self._price_cache.get(cache_key)
        if cached is not None:
            return cached

        result = massive_client.price_bars(
            ticker, period=period, adjusted=True, round_dp=4,
        )

        if result:
            self._price_cache.set(cache_key, result)
        logger.info(f"Fetched {len(result)} total-return bars for {ticker} ({period})")
        return result

    def get_price_history(self, ticker: str, period: str = "6mo") -> list[dict]:
        cache_key = f"{ticker}:{period}"
        cached = self._price_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Returning cached price history for {ticker}")
            return cached

        # Unadjusted, 2dp — matches the old yfinance get_price_history shape.
        result = massive_client.price_bars(
            ticker, period=period, adjusted=False, round_dp=2,
        )

        if result:
            self._price_cache.set(cache_key, result)
        logger.info(f"Fetched {len(result)} price bars for {ticker} ({period})")
        return result

    def get_fundamentals(self, ticker: str) -> dict:
        cached = self._fundamentals_cache.get(ticker)
        if cached is not None:
            logger.debug(f"Returning cached fundamentals for {ticker}")
            return cached

        result = self._compute_fundamentals(ticker)
        self._fundamentals_cache.set(ticker, result)
        logger.info(f"Fetched fundamentals for {ticker}")
        return result

    # ── Fundamentals computation (Massive financials -> ratios) ────────────

    @staticmethod
    def _statements(report: dict) -> tuple[dict, dict, dict]:
        """Unwrap a single financials report into its three statement dicts."""
        fin = (report or {}).get("financials") or {}
        income = fin.get("income_statement") or {}
        balance = fin.get("balance_sheet") or {}
        cash = fin.get("cash_flow_statement") or {}
        return income, balance, cash

    @classmethod
    def _latest_revenue_growth(cls, reports: list) -> float | None:
        """(rev - prev_rev) / prev_rev from the two most recent reports.

        `reports` is massive.financials() output, ordered desc (newest first).
        Returns None if either revenue is missing/zero.
        """
        if not isinstance(reports, list) or len(reports) < 2:
            return None
        inc0, _, _ = cls._statements(reports[0])
        inc1, _, _ = cls._statements(reports[1])
        rev = _safe_float(_g(inc0, "revenues", "revenue"))
        prev_rev = _safe_float(_g(inc1, "revenues", "revenue"))
        if rev is None or prev_rev in (None, 0):
            return None
        return round((rev - prev_rev) / prev_rev, 4)

    def _compute_fundamentals(self, ticker: str) -> dict:
        """Build the exact fundamentals dict from Massive sources.

        Computed (best-effort, defensive — any missing input -> None for that
        field, never a crash):
          pe_ratio       = price / EPS,  EPS = net_income / shares
          pb_ratio       = market_cap / total_equity
          ev_ebitda      = (market_cap + total_debt - cash) / EBITDA
          profit_margin  = net_income / revenue
          revenue_growth = (rev - prev_rev) / prev_rev
          debt_to_equity = total_debt / total_equity
          free_cash_flow = operating_cash_flow - capex
          beta           = massive.compute_beta(ticker vs SPY)
          market_cap / shares / sector = ticker_reference
          current_price  = massive.last_price
          52w_high/low   = max/min close over 1y of price bars

        REDUCED (no Massive source -> None):
          forward_pe, short_ratio, bid, ask, float_shares, dividend_yield
          (dividend_yield is left None — the dividends endpoint isn't wired
          here; computing it cheaply isn't possible without it).
        """
        # Exact key contract — start all None, fill what we can.
        out: dict = {
            "pe_ratio": None,
            "forward_pe": None,        # GAP: no Massive forward EPS estimate
            "pb_ratio": None,
            "ev_ebitda": None,
            "market_cap": None,
            "revenue_growth": None,
            "profit_margin": None,
            "debt_to_equity": None,
            "free_cash_flow": None,
            "dividend_yield": None,    # GAP: dividends endpoint not wired here
            "beta": None,
            "52w_high": None,
            "52w_low": None,
            "short_ratio": None,       # GAP: no Massive short-interest source
            "sector": None,
            "industry": None,
            "current_price": None,
            "avg_volume_10d": None,
            "avg_volume_3m": None,
            "bid": None,               # GAP: quote bid not surfaced here
            "ask": None,               # GAP: quote ask not surfaced here
            "shares_outstanding": None,
            "float_shares": None,      # GAP: no Massive float source
        }

        # ── Reference details: market_cap, shares, sector, industry ────────
        ref: dict = {}
        try:
            ref = massive_client.ticker_reference(ticker) or {}
        except Exception as e:
            logger.warning("ticker_reference failed for %s: %s", ticker, e)
        market_cap = _safe_float(ref.get("market_cap"))
        out["market_cap"] = market_cap
        out["sector"] = ref.get("sector")
        # Massive has no GICS industry; sic_description is the closest proxy
        # (same field used for sector). Kept distinct so the key exists.
        out["industry"] = ref.get("sic_description") or ref.get("sector")
        shares = (
            _safe_float(ref.get("weighted_shares_outstanding"))
            or _safe_float(ref.get("share_class_shares_outstanding"))
        )
        out["shares_outstanding"] = shares

        # ── Current price ──────────────────────────────────────────────────
        current_price = None
        try:
            current_price = _safe_float(massive_client.last_price(ticker))
        except Exception as e:
            logger.warning("last_price failed for %s: %s", ticker, e)
        out["current_price"] = current_price

        # ── Financials-derived ratios ──────────────────────────────────────
        reports: list = []
        try:
            reports = massive_client.financials(ticker, limit=8) or []
        except Exception as e:
            logger.warning("financials failed for %s: %s", ticker, e)

        if reports:
            inc, bal, cf = self._statements(reports[0])

            net_income = _safe_float(
                _g(inc, "net_income_loss", "net_income_loss_attributable_to_parent",
                   "net_income")
            )
            revenue = _safe_float(_g(inc, "revenues", "revenue"))
            ebitda = _safe_float(_g(inc, "ebitda"))

            total_equity = _safe_float(
                _g(bal, "equity_attributable_to_parent", "equity",
                   "stockholders_equity")
            )
            total_debt = _safe_float(
                _g(bal, "long_term_debt", "debt", "total_debt")
            )
            cash_and_equiv = _safe_float(
                _g(bal, "cash", "cash_and_equivalents",
                   "cash_and_cash_equivalents")
            )

            op_cashflow = _safe_float(
                _g(cf, "net_cash_flow_from_operating_activities",
                   "operating_cash_flow")
            )
            capex = _safe_float(
                _g(cf, "capital_expenditure", "payments_to_acquire_ppe")
            )

            # profit_margin = net_income / revenue
            if net_income is not None and revenue not in (None, 0):
                out["profit_margin"] = round(net_income / revenue, 4)

            # pe_ratio = price / (net_income / shares)
            if (current_price is not None and net_income not in (None, 0)
                    and shares not in (None, 0)):
                eps = net_income / shares
                if eps not in (None, 0):
                    out["pe_ratio"] = round(current_price / eps, 4)

            # pb_ratio = market_cap / total_equity
            if market_cap is not None and total_equity not in (None, 0):
                out["pb_ratio"] = round(market_cap / total_equity, 4)

            # debt_to_equity = total_debt / total_equity
            if total_debt is not None and total_equity not in (None, 0):
                out["debt_to_equity"] = round(total_debt / total_equity, 4)

            # ev_ebitda = (market_cap + total_debt - cash) / EBITDA
            if (market_cap is not None and ebitda not in (None, 0)):
                ev = market_cap + (total_debt or 0.0) - (cash_and_equiv or 0.0)
                out["ev_ebitda"] = round(ev / ebitda, 4)

            # free_cash_flow = operating_cash_flow - capex
            # (capex is typically reported negative; subtract its magnitude)
            if op_cashflow is not None:
                fcf = op_cashflow - abs(capex) if capex is not None else op_cashflow
                out["free_cash_flow"] = round(fcf, 2)

            # revenue_growth from the two latest reports
            out["revenue_growth"] = self._latest_revenue_growth(reports)

        # ── Beta vs SPY ────────────────────────────────────────────────────
        try:
            out["beta"] = massive_client.compute_beta(ticker, benchmark="SPY", period="1y")
        except Exception as e:
            logger.warning("compute_beta failed for %s: %s", ticker, e)

        # ── 52-week high/low + avg volume from 1y of price bars ────────────
        try:
            bars = massive_client.price_bars(ticker, period="1y", adjusted=False, round_dp=2)
        except Exception as e:
            logger.warning("price_bars(1y) failed for %s: %s", ticker, e)
            bars = []
        if bars:
            highs = [b["high"] for b in bars if b.get("high") is not None]
            lows = [b["low"] for b in bars if b.get("low") is not None]
            vols = [b["volume"] for b in bars if b.get("volume") is not None]
            if highs:
                out["52w_high"] = round(max(highs), 2)
            if lows:
                out["52w_low"] = round(min(lows), 2)
            if vols:
                # avg_volume_3m ~ last ~63 trading days; 10d ~ last 10.
                last10 = vols[-10:]
                last63 = vols[-63:]
                if last10:
                    out["avg_volume_10d"] = int(sum(last10) / len(last10))
                if last63:
                    out["avg_volume_3m"] = int(sum(last63) / len(last63))

        return out

    def get_options_chain(self, ticker: str, expiry: str | None = None) -> dict:
        cache_key = f"{ticker}:{expiry or 'nearest'}"
        cached = self._options_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Returning cached options chain for {ticker}")
            return cached

        # massive.options_snapshot already returns the canonical shape
        # {expiration, all_expirations, calls[], puts[]} and trims ~30 NTM
        # contracts each side, mirroring the old yfinance behavior. On failure
        # it returns {"expirations": [], "calls": [], "puts": []} — same empty
        # shape the old client returned.
        result = massive_client.options_snapshot(ticker, expiry=expiry)

        self._options_cache.set(cache_key, result)
        logger.info(f"Fetched options chain for {ticker} exp={result.get('expiration')}")
        return result

    # ── Async interface ───────────────────────────────────────────
    # Route handlers / orchestrator MUST use these; they free the event loop
    # while the blocking HTTP call runs on a thread.

    async def aget_price_history(self, ticker: str, period: str = "6mo") -> list[dict]:
        return await run_sync(self.get_price_history, ticker, period)

    async def aget_fundamentals(self, ticker: str) -> dict:
        return await run_sync(self.get_fundamentals, ticker)

    async def aget_options_chain(self, ticker: str, expiry: str | None = None) -> dict:
        return await run_sync(self.get_options_chain, ticker, expiry)
