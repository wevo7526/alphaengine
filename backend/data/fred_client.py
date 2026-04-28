"""
FRED (Federal Reserve Economic Data) client.

Provides macro-economic indicators that the Macro Regime Analyst uses
to classify the current environment as expansion, late-cycle, contraction,
or recovery.

Rate limit: 120 requests/minute (generous, but we still cache).

Stability notes:
  - fredapi is synchronous and makes HTTPS calls. Sync methods are safe from
    worker threads; async wrappers dispatch to run_sync so the event loop
    stays free.
  - Caches are bounded to prevent unbounded heap growth.
  - Retry uses async sleep when called from async paths. The sync fallback
    stays simple because it only runs from thread-pool workers.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone

from fredapi import Fred

from config import settings
from infra.async_utils import run_sync
from infra.cache import TTLCache

logger = logging.getLogger(__name__)


def _retry_fetch(fn, retries: int = 2, base_delay: float = 0.8):
    """Retry a FRED API call with jittered backoff."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            result = fn()
            if result is not None:
                return result
        except Exception as e:
            last_exc = e
            logger.debug(f"FRED retry {attempt + 1}/{retries}: {e}")
        if attempt < retries:
            wait = base_delay * (2 ** attempt) + random.uniform(0, 0.3)
            time.sleep(wait)
    if last_exc is not None:
        raise last_exc
    return None


# Series IDs mapped to human-readable names.
MACRO_SERIES = {
    "DFF": "fed_funds_rate",           # Monetary policy stance
    "T10Y2Y": "yield_curve_spread",    # Inversion = recession signal
    "T10YIE": "breakeven_inflation",   # Market inflation expectations
    "BAMLH0A0HYM2": "credit_spreads",  # Risk appetite (wide = fear)
    "VIXCLS": "vix",                   # Implied volatility / fear gauge
    "UNRATE": "unemployment",          # Labor market health (monthly)
    "CPIAUCSL": "cpi",                 # Inflation level (monthly)
    "GDP": "real_gdp",                 # Growth trajectory (quarterly)
    "WALCL": "fed_balance_sheet",      # Liquidity conditions (weekly)
    "DCOILWTICO": "wti_crude",         # Energy / inflation input
    "DTWEXBGS": "usd_index",           # Dollar strength
    "M2SL": "m2_money_supply",         # Monetary aggregate (monthly)
    "ICSA": "jobless_claims",          # High-frequency labor signal (weekly)
}


class FREDDataClient:
    _SNAPSHOT_TTL = 3600
    _SERIES_TTL = 3600
    _SINGLE_TTL = 900

    def __init__(self):
        self.fred = Fred(api_key=settings.FRED_API_KEY)
        # One-slot "cache" for the full snapshot so concurrent requests share.
        self._snapshot_cache: dict | None = None
        self._snapshot_timestamp: float = 0
        self._series_cache: TTLCache[list[dict]] = TTLCache(
            max_entries=256, ttl_seconds=self._SERIES_TTL,
        )
        self._single_cache: TTLCache[dict] = TTLCache(
            max_entries=128, ttl_seconds=self._SINGLE_TTL,
        )

    def get_macro_snapshot(self) -> dict:
        """Pull latest values for all key macro indicators."""
        now = time.time()
        if self._snapshot_cache and (now - self._snapshot_timestamp) < self._SNAPSHOT_TTL:
            logger.debug("Returning cached macro snapshot")
            return self._snapshot_cache

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _fetch_one(series_id: str, name: str) -> tuple[str, dict | None]:
            try:
                series = _retry_fetch(lambda sid=series_id: self.fred.get_series(sid))
                if series is None:
                    return name, None
                series = series.dropna()
                if len(series) < 2:
                    return name, None
                return name, {
                    "value": float(series.iloc[-1]),
                    "previous": float(series.iloc[-2]),
                    "change": float(series.iloc[-1] - series.iloc[-2]),
                    "date": str(series.index[-1].date()),
                    "series_id": series_id,
                }
            except Exception as e:
                logger.warning(f"Failed to fetch {series_id} ({name}): {e}")
                return name, None

        snapshot: dict = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(_fetch_one, sid, name): name
                for sid, name in MACRO_SERIES.items()
            }
            for future in as_completed(futures):
                try:
                    name, data = future.result(timeout=30)
                except Exception as e:
                    logger.warning(f"FRED worker failure: {e}")
                    continue
                if data:
                    snapshot[name] = data

        self._snapshot_cache = snapshot
        self._snapshot_timestamp = now
        logger.info(f"Macro snapshot built: {len(snapshot)}/{len(MACRO_SERIES)} indicators")
        return snapshot

    def get_series_history(self, series_id: str, lookback_days: int = 252) -> list[dict]:
        cache_key = f"{series_id}:{lookback_days}"
        cached = self._series_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Returning cached series {series_id}")
            return cached

        start = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        try:
            series = _retry_fetch(
                lambda: self.fred.get_series(series_id, observation_start=start)
            )
        except Exception as e:
            logger.warning(f"FRED series {series_id} failed: {e}")
            return []
        if series is None:
            return []
        series = series.dropna()
        result = [
            {"date": str(idx.date()), "value": float(val)}
            for idx, val in series.items()
        ]
        self._series_cache.set(cache_key, result)
        logger.info(f"Fetched {len(result)} observations for {series_id}")
        return result

    def get_risk_free_rate(self) -> float:
        """
        Fetch current 3-month Treasury yield (DGS3MO) as the risk-free rate.

        Falls back to 4% if FRED is unreachable. Result is decimal (0.045 for
        4.5%) and cached via the underlying single-indicator cache (1h TTL),
        so this is cheap to call repeatedly.

        Why DGS3MO and not Fed funds: Treasuries are the textbook risk-free
        proxy for Sharpe-style calculations, and DGS3MO closely tracks the
        Fed funds path while being a true tradable rate.
        """
        try:
            data = self.get_single_indicator("DGS3MO")
            if data and data.get("value") is not None:
                # FRED returns DGS3MO as a percentage (e.g. 5.25 for 5.25%)
                pct = float(data["value"])
                if 0 < pct < 25:  # sanity bounds
                    return pct / 100.0
        except Exception as e:
            logger.warning(f"get_risk_free_rate fallback to 4% (FRED failed: {e})")
        return 0.04

    def get_single_indicator(self, series_id: str) -> dict | None:
        cached = self._single_cache.get(series_id)
        if cached is not None:
            return cached
        try:
            series = _retry_fetch(lambda: self.fred.get_series(series_id))
            if series is None:
                return None
            series = series.dropna()
            if len(series) < 2:
                return None
            data = {
                "value": float(series.iloc[-1]),
                "previous": float(series.iloc[-2]),
                "change": float(series.iloc[-1] - series.iloc[-2]),
                "date": str(series.index[-1].date()),
                "series_id": series_id,
            }
            self._single_cache.set(series_id, data)
            return data
        except Exception as e:
            logger.warning(f"Failed to fetch {series_id}: {e}")
            return None

    # ── Async wrappers ────────────────────────────────────────────
    # Snapshot internally uses a ThreadPoolExecutor, so calling it from
    # within `run_sync` (itself in a thread) is still safe — threads can
    # spawn threads.

    async def aget_macro_snapshot(self) -> dict:
        return await run_sync(self.get_macro_snapshot)

    async def aget_series_history(self, series_id: str, lookback_days: int = 252) -> list[dict]:
        return await run_sync(self.get_series_history, series_id, lookback_days)

    async def aget_single_indicator(self, series_id: str) -> dict | None:
        return await run_sync(self.get_single_indicator, series_id)
