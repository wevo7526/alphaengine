"""
Alpha Vantage client for pre-computed technical indicators.

CRITICAL: 25 requests/day on free tier. Every call counts.
Cache TTL is 4 hours — technical indicators on daily bars don't change
intraday, so there's zero reason to re-fetch.

Used by the Quant Strategist for supplementary technical analysis
(SMA, EMA, RSI, MACD, Bollinger Bands). The Quant Agent can also compute
these from raw price data via market_client, so Alpha Vantage is a
convenience layer, not a hard dependency.

Stability notes:
  - All HTTP calls use infra.http with retries and sensible timeouts.
  - On quota breach (JSON "Note"/"Information" fields), we return {} AND
    log the message so operators can see when they've hit the daily wall.
"""

from __future__ import annotations

import logging

from config import settings
from infra.async_utils import run_sync
from infra.cache import TTLCache
from infra.http import HttpError, http_get_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"
_INDICATOR_TTL = 14400  # 4h


class AlphaVantageClient:
    def __init__(self):
        self.api_key = settings.ALPHA_VANTAGE_KEY
        self._cache: TTLCache[dict] = TTLCache(max_entries=256, ttl_seconds=_INDICATOR_TTL)

    def _fetch(self, params: dict) -> dict:
        if not self.api_key:
            logger.debug("ALPHA_VANTAGE_KEY not set — skipping")
            return {}

        cache_key = "|".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey")
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Returning cached AV data: {cache_key}")
            return cached

        params["apikey"] = self.api_key
        try:
            data = http_get_json(
                _BASE_URL,
                params=params,
                read_timeout=15,
                total_timeout=20,
                max_retries=2,
                label=f"alphavantage({params.get('function')})",
            )
        except HttpError as e:
            logger.warning(f"Alpha Vantage fetch failed: {e}")
            return {}

        if not isinstance(data, dict):
            logger.warning(f"Alpha Vantage returned non-dict payload: {type(data).__name__}")
            return {}

        # Alpha Vantage signals quota / errors in JSON body, not HTTP status.
        if "Note" in data or "Information" in data or "Error Message" in data:
            msg = data.get("Note") or data.get("Information") or data.get("Error Message")
            logger.warning(f"Alpha Vantage rate limit or error: {msg}")
            return {}

        # Trim time-series payloads to 20 most recent points so we don't
        # blow the LLM context budget.
        for key in list(data.keys()):
            if key.startswith("Technical Analysis") or key.startswith("Meta"):
                if isinstance(data[key], dict) and len(data[key]) > 20:
                    data[key] = dict(list(data[key].items())[:20])

        self._cache.set(cache_key, data)
        return data

    def get_rsi(self, ticker: str, period: int = 14) -> dict:
        return self._fetch({
            "function": "RSI", "symbol": ticker, "interval": "daily",
            "time_period": str(period), "series_type": "close",
        })

    def get_macd(self, ticker: str) -> dict:
        return self._fetch({
            "function": "MACD", "symbol": ticker, "interval": "daily",
            "series_type": "close",
        })

    def get_bollinger_bands(self, ticker: str, period: int = 20) -> dict:
        return self._fetch({
            "function": "BBANDS", "symbol": ticker, "interval": "daily",
            "time_period": str(period), "series_type": "close",
        })

    def get_sma(self, ticker: str, period: int = 50) -> dict:
        return self._fetch({
            "function": "SMA", "symbol": ticker, "interval": "daily",
            "time_period": str(period), "series_type": "close",
        })

    def get_ema(self, ticker: str, period: int = 20) -> dict:
        return self._fetch({
            "function": "EMA", "symbol": ticker, "interval": "daily",
            "time_period": str(period), "series_type": "close",
        })

    # ── Async wrappers ────────────────────────────────────────────

    async def aget_rsi(self, ticker: str, period: int = 14) -> dict:
        return await run_sync(self.get_rsi, ticker, period)

    async def aget_macd(self, ticker: str) -> dict:
        return await run_sync(self.get_macd, ticker)

    async def aget_bollinger_bands(self, ticker: str, period: int = 20) -> dict:
        return await run_sync(self.get_bollinger_bands, ticker, period)

    async def aget_sma(self, ticker: str, period: int = 50) -> dict:
        return await run_sync(self.get_sma, ticker, period)

    async def aget_ema(self, ticker: str, period: int = 20) -> dict:
        return await run_sync(self.get_ema, ticker, period)
