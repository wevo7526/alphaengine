"""
Market data client via Yahoo Finance (yfinance).

No API key required. Provides price history, fundamentals, and options chains.
Used by the Fundamental Agent, Options Flow Agent, and Quant Strategist.

Stability notes:
  - yfinance is a synchronous library that makes HTTP calls. All calls MUST
    go through `run_sync` when invoked from an async context; otherwise a
    slow Yahoo response blocks the entire event loop.
  - yfinance throttles around ~2000 requests/hour. We cache aggressively and
    use a bounded TTLCache so a long-running process doesn't grow without
    bound.
  - Transient yfinance errors (empty DataFrame, network glitch) get one retry
    with backoff. Past that the cache's last-good value is returned if
    available, otherwise the caller gets an explicit error shape.
"""

from __future__ import annotations

import logging
import random
import time

import yfinance as yf

from infra.async_utils import run_sync
from infra.cache import TTLCache

logger = logging.getLogger(__name__)

# Cache TTL in seconds
_PRICE_TTL = 900        # 15 min — prices move, but agents don't need tick-level
_FUNDAMENTALS_TTL = 3600  # 1 hour — fundamentals update at most daily
_OPTIONS_TTL = 900      # 15 min — options chains shift intraday

# Bounded sizes: a single user can touch O(100) tickers × periods in a scan.
# 512 entries per cache × ~5 KB each = <3 MB ceiling.
_PRICE_MAX = 512
_FUNDAMENTALS_MAX = 512
_OPTIONS_MAX = 256


def _safe_float(v) -> float | None:
    """Coerce yfinance/pandas scalars to plain floats. NaN -> None."""
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _retry_sync(fn, retries: int = 1, label: str = "yfinance"):
    """Single retry with jittered backoff for yfinance calls."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:  # yfinance raises a zoo of exceptions; catch broadly but log
            last_exc = e
            if attempt < retries:
                wait = 0.5 + random.uniform(0, 0.5)
                logger.warning(f"[{label}] transient error, retry {attempt + 1}/{retries}: {e}")
                time.sleep(wait)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"[{label}] unreachable")


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
        Next earnings date + last reported date for a ticker, plus EPS
        actuals/estimates when available. Cached on the same TTL as
        fundamentals — earnings calendars don't move daily.

        Replaces LLM-hallucinated catalyst dates ("Q2 earnings July 25")
        with tool-verified ones.
        """
        cache_key = f"EARN:{ticker}"
        cached = self._fundamentals_cache.get(cache_key)
        if cached is not None:
            return cached

        def _fetch() -> dict:
            stock = yf.Ticker(ticker)
            out: dict = {"ticker": ticker.upper()}
            # Calendar — yfinance returns a DataFrame with "Earnings Date" col
            try:
                cal = stock.calendar
                if cal is not None:
                    if hasattr(cal, "to_dict"):  # DataFrame
                        d = cal.to_dict()
                        # Extract first earnings date if present
                        ed = d.get("Earnings Date") or d.get("earningsDate")
                        if ed:
                            vals = list(ed.values()) if isinstance(ed, dict) else list(ed)
                            if vals:
                                out["next_earnings_date"] = str(vals[0])
                    elif isinstance(cal, dict):
                        ed = cal.get("Earnings Date") or cal.get("earningsDate")
                        if ed:
                            vals = ed if isinstance(ed, list) else [ed]
                            out["next_earnings_date"] = str(vals[0])
            except Exception as e:
                logger.debug(f"earnings calendar fetch (cal) {ticker}: {e}")
            # Earnings dates DataFrame — historical actual vs estimate
            try:
                ed = stock.earnings_dates
                if ed is not None and hasattr(ed, "head"):
                    rows = []
                    for idx, row in ed.head(8).iterrows():
                        rows.append({
                            "date": str(idx.date()) if hasattr(idx, "date") else str(idx),
                            "eps_estimate": _safe_float(row.get("EPS Estimate")),
                            "eps_actual": _safe_float(row.get("Reported EPS")),
                            "surprise_pct": _safe_float(row.get("Surprise(%)")),
                        })
                    out["recent_earnings"] = rows
                    # Most recent past report
                    past = [r for r in rows if r.get("eps_actual") is not None]
                    if past:
                        out["last_reported"] = past[0]
                    # Next upcoming
                    upcoming = [r for r in rows if r.get("eps_actual") is None]
                    if upcoming:
                        out.setdefault("next_earnings_date", upcoming[-1]["date"])
            except Exception as e:
                logger.debug(f"earnings calendar fetch (dates) {ticker}: {e}")
            return out

        try:
            result = _retry_sync(_fetch, label=f"yf.calendar({ticker})")
        except Exception as e:
            logger.warning(f"earnings calendar failed for {ticker}: {e}")
            return {"ticker": ticker.upper(), "error": str(e)}

        self._fundamentals_cache.set(cache_key, result)
        return result

    def get_consensus(self, ticker: str) -> dict:
        """
        Analyst consensus (target price, recommendation, EPS forward).
        Pulled from yfinance `info` — no separate API call required.

        Returns target_mean / target_high / target_low / num_analysts /
        recommendation_key + forward EPS estimate.
        """
        cache_key = f"CONS:{ticker}"
        cached = self._fundamentals_cache.get(cache_key)
        if cached is not None:
            return cached

        def _fetch() -> dict:
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            current = info.get("currentPrice") or info.get("regularMarketPrice")
            target_mean = info.get("targetMeanPrice")
            implied = None
            if target_mean and current and current > 0:
                implied = round((target_mean - current) / current * 100, 2)
            return {
                "ticker": ticker.upper(),
                "current_price": current,
                "target_mean": target_mean,
                "target_high": info.get("targetHighPrice"),
                "target_low": info.get("targetLowPrice"),
                "target_median": info.get("targetMedianPrice"),
                "num_analysts": info.get("numberOfAnalystOpinions"),
                "recommendation_mean": info.get("recommendationMean"),
                "recommendation_key": info.get("recommendationKey"),
                "forward_eps": info.get("forwardEps"),
                "trailing_eps": info.get("trailingEps"),
                "earnings_growth": info.get("earningsGrowth"),
                "revenue_growth": info.get("revenueGrowth"),
                "implied_upside_pct": implied,
            }

        try:
            result = _retry_sync(_fetch, label=f"yf.consensus({ticker})")
        except Exception as e:
            logger.warning(f"consensus fetch failed for {ticker}: {e}")
            return {"ticker": ticker.upper(), "error": str(e)}

        self._fundamentals_cache.set(cache_key, result)
        return result

    def get_total_return_history(self, ticker: str, period: str = "1y") -> list[dict]:
        """
        Total-return-adjusted price history. Adjusted for splits AND
        dividends — used by the backtester so dividend-paying names don't
        understate strategy returns by 2-5%/yr.

        Cached separately from `get_price_history` (which keeps unadjusted
        closes for live UI / mark-to-market display).
        """
        cache_key = f"TR:{ticker}:{period}"
        cached = self._price_cache.get(cache_key)
        if cached is not None:
            return cached

        def _fetch() -> list[dict]:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period, auto_adjust=True, actions=False)
            if df is None or df.empty:
                return []
            return [
                {
                    "date": str(idx.date()),
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row["Volume"]),
                }
                for idx, row in df.iterrows()
            ]

        try:
            result = _retry_sync(_fetch, label=f"yf.history({ticker},auto_adjust)")
        except Exception as e:
            logger.warning(f"yfinance total-return history failed for {ticker}: {e}")
            return []

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

        def _fetch() -> list[dict]:
            stock = yf.Ticker(ticker)
            df = stock.history(period=period)
            if df is None or df.empty:
                return []
            return [
                {
                    "date": str(idx.date()),
                    "open": round(float(row["Open"]), 2),
                    "high": round(float(row["High"]), 2),
                    "low": round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                    "volume": int(row["Volume"]),
                }
                for idx, row in df.iterrows()
            ]

        try:
            result = _retry_sync(_fetch, label=f"yf.history({ticker})")
        except Exception as e:
            logger.warning(f"yfinance price history failed for {ticker}: {e}")
            return []

        if result:
            self._price_cache.set(cache_key, result)
        logger.info(f"Fetched {len(result)} price bars for {ticker} ({period})")
        return result

    def get_fundamentals(self, ticker: str) -> dict:
        cached = self._fundamentals_cache.get(ticker)
        if cached is not None:
            logger.debug(f"Returning cached fundamentals for {ticker}")
            return cached

        def _fetch() -> dict:
            stock = yf.Ticker(ticker)
            info = stock.info or {}
            return {
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "pb_ratio": info.get("priceToBook"),
                "ev_ebitda": info.get("enterpriseToEbitda"),
                "market_cap": info.get("marketCap"),
                "revenue_growth": info.get("revenueGrowth"),
                "profit_margin": info.get("profitMargins"),
                "debt_to_equity": info.get("debtToEquity"),
                "free_cash_flow": info.get("freeCashflow"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta"),
                "52w_high": info.get("fiftyTwoWeekHigh"),
                "52w_low": info.get("fiftyTwoWeekLow"),
                "short_ratio": info.get("shortRatio"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                # Liquidity inputs: average daily volume + bid/ask + float
                "avg_volume_10d": info.get("averageDailyVolume10Day") or info.get("averageVolume10days"),
                "avg_volume_3m": info.get("averageVolume") or info.get("averageDailyVolume3Month"),
                "bid": info.get("bid"),
                "ask": info.get("ask"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "float_shares": info.get("floatShares"),
            }

        try:
            result = _retry_sync(_fetch, label=f"yf.info({ticker})")
        except Exception as e:
            logger.warning(f"yfinance fundamentals failed for {ticker}: {e}")
            return {}

        self._fundamentals_cache.set(ticker, result)
        logger.info(f"Fetched fundamentals for {ticker}")
        return result

    def get_options_chain(self, ticker: str, expiry: str | None = None) -> dict:
        cache_key = f"{ticker}:{expiry or 'nearest'}"
        cached = self._options_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Returning cached options chain for {ticker}")
            return cached

        def _fetch() -> dict:
            stock = yf.Ticker(ticker)
            expirations = stock.options or ()
            if not expirations:
                return {"expirations": [], "calls": [], "puts": []}
            target = expiry or expirations[0]
            chain = stock.option_chain(target)

            call_cols = ["strike", "lastPrice", "bid", "ask", "volume", "openInterest", "impliedVolatility"]
            put_cols = call_cols
            calls_df = chain.calls[call_cols] if all(c in chain.calls.columns for c in call_cols) else chain.calls
            puts_df = chain.puts[put_cols] if all(c in chain.puts.columns for c in put_cols) else chain.puts

            calls_list = calls_df.to_dict(orient="records")
            puts_list = puts_df.to_dict(orient="records")
            if len(calls_list) > 30:
                mid = len(calls_list) // 2
                calls_list = calls_list[mid - 15: mid + 15]
            if len(puts_list) > 30:
                mid = len(puts_list) // 2
                puts_list = puts_list[mid - 15: mid + 15]

            return {
                "expiration": target,
                "all_expirations": list(expirations[:5]),
                "calls": calls_list,
                "puts": puts_list,
            }

        try:
            result = _retry_sync(_fetch, label=f"yf.options({ticker})")
        except Exception as e:
            logger.warning(f"yfinance options chain failed for {ticker}: {e}")
            return {"expirations": [], "calls": [], "puts": []}

        self._options_cache.set(cache_key, result)
        logger.info(f"Fetched options chain for {ticker} exp={result.get('expiration')}")
        return result

    # ── Async interface ───────────────────────────────────────────
    # Route handlers / orchestrator MUST use these; they free the event loop
    # while the blocking yfinance call runs on a thread.

    async def aget_price_history(self, ticker: str, period: str = "6mo") -> list[dict]:
        return await run_sync(self.get_price_history, ticker, period)

    async def aget_fundamentals(self, ticker: str) -> dict:
        return await run_sync(self.get_fundamentals, ticker)

    async def aget_options_chain(self, ticker: str, expiry: str | None = None) -> dict:
        return await run_sync(self.get_options_chain, ticker, expiry)
