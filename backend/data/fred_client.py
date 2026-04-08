"""
FRED (Federal Reserve Economic Data) client.

Provides macro-economic indicators that the Macro Regime Analyst uses
to classify the current environment as expansion, late-cycle, contraction,
or recovery.

Rate limit: 120 requests/minute (generous, but we still cache).
"""

from fredapi import Fred
from datetime import datetime, timedelta
import logging
import time

from config import settings

logger = logging.getLogger(__name__)


def _retry_fetch(fn, retries=2, delay=1.0):
    """Retry a FRED API call — their server is intermittently flaky."""
    for attempt in range(retries + 1):
        try:
            result = fn()
            if result is not None:
                return result
        except Exception as e:
            if attempt < retries:
                time.sleep(delay)
                continue
            raise e
    return None

# Series IDs mapped to human-readable names.
# Each of these tells the Macro Agent something specific about the regime.
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
    def __init__(self):
        self.fred = Fred(api_key=settings.FRED_API_KEY)
        self._snapshot_cache: dict | None = None
        self._snapshot_timestamp: float = 0
        self._series_cache: dict[str, tuple[float, object]] = {}

    # Cache TTL: macro data updates at most daily, so 1 hour is safe
    _SNAPSHOT_TTL = 3600  # seconds
    _SERIES_TTL = 3600

    def get_macro_snapshot(self) -> dict:
        """
        Pull latest values for all key macro indicators in a single call.

        Returns a dict of indicator snapshots, each with:
          - value: most recent observation
          - previous: prior observation
          - change: delta between them
          - date: observation date

        This is the Macro Agent's primary input. One call here replaces
        what would otherwise be 13 separate API requests, and the result
        is cached for 1 hour since macro data doesn't update intraday.
        """
        now = time.time()
        if self._snapshot_cache and (now - self._snapshot_timestamp) < self._SNAPSHOT_TTL:
            logger.debug("Returning cached macro snapshot")
            return self._snapshot_cache

        snapshot = {}
        for series_id, name in MACRO_SERIES.items():
            try:
                series = _retry_fetch(lambda sid=series_id: self.fred.get_series(sid))
                if series is None:
                    continue
                series = series.dropna()
                if len(series) < 2:
                    continue
                snapshot[name] = {
                    "value": float(series.iloc[-1]),
                    "previous": float(series.iloc[-2]),
                    "change": float(series.iloc[-1] - series.iloc[-2]),
                    "date": str(series.index[-1].date()),
                    "series_id": series_id,
                }
            except Exception as e:
                logger.warning(f"Failed to fetch {series_id} ({name}): {e}")
                continue

        self._snapshot_cache = snapshot
        self._snapshot_timestamp = now
        logger.info(f"Macro snapshot built: {len(snapshot)}/{len(MACRO_SERIES)} indicators")
        return snapshot

    def get_series_history(
        self,
        series_id: str,
        lookback_days: int = 252,
    ) -> list[dict]:
        """
        Pull historical data for a single FRED series.

        Default lookback is 252 trading days (~1 year). Returns a list of
        {date, value} dicts for easy serialization.

        Used by the Macro Agent for trend analysis — is the yield curve
        steepening or flattening? Are credit spreads widening or tightening?
        The direction matters more than the level.
        """
        now = time.time()
        cache_key = f"{series_id}:{lookback_days}"
        if cache_key in self._series_cache:
            ts, data = self._series_cache[cache_key]
            if (now - ts) < self._SERIES_TTL:
                logger.debug(f"Returning cached series {series_id}")
                return data

        start = datetime.utcnow() - timedelta(days=lookback_days)
        series = _retry_fetch(
            lambda: self.fred.get_series(series_id, observation_start=start)
        )
        if series is None:
            return []
        series = series.dropna()

        result = [
            {"date": str(idx.date()), "value": float(val)}
            for idx, val in series.items()
        ]

        self._series_cache[cache_key] = (now, result)
        logger.info(f"Fetched {len(result)} observations for {series_id}")
        return result

    def get_single_indicator(self, series_id: str) -> dict | None:
        """
        Get the latest value for a single indicator.

        Useful when an agent needs just one data point (e.g., current VIX)
        without pulling the entire macro snapshot.
        """
        try:
            series = self.fred.get_series(series_id).dropna()
            if len(series) < 2:
                return None
            return {
                "value": float(series.iloc[-1]),
                "previous": float(series.iloc[-2]),
                "change": float(series.iloc[-1] - series.iloc[-2]),
                "date": str(series.index[-1].date()),
                "series_id": series_id,
            }
        except Exception as e:
            logger.warning(f"Failed to fetch {series_id}: {e}")
            return None
