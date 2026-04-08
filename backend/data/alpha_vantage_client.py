"""
Alpha Vantage client for pre-computed technical indicators.

CRITICAL: 25 requests/day on free tier. Every call counts.
Cache TTL is 4 hours — technical indicators on daily bars don't change
intraday, so there's zero reason to re-fetch.

Used by the Quant Strategist for supplementary technical analysis
(SMA, EMA, RSI, MACD, Bollinger Bands). The Quant Agent can also
compute these from raw price data via market_client, so Alpha Vantage
is a convenience layer, not a hard dependency.
"""

import httpx
import time
import logging

from config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.alphavantage.co/query"

# 4-hour cache — daily indicators don't change intraday
_INDICATOR_TTL = 14400


class AlphaVantageClient:
    def __init__(self):
        self.api_key = settings.ALPHA_VANTAGE_KEY
        self._cache: dict[str, tuple[float, dict]] = {}

    def _fetch(self, params: dict) -> dict:
        """
        Single fetch method — all Alpha Vantage calls go through here
        so caching and rate-limit awareness are centralized.
        """
        cache_key = "|".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "apikey")

        now = time.time()
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if (now - ts) < _INDICATOR_TTL:
                logger.debug(f"Returning cached AV data: {cache_key}")
                return data

        params["apikey"] = self.api_key

        try:
            resp = httpx.get(_BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"Alpha Vantage fetch failed: {e}")
            return {}

        # Alpha Vantage returns error messages in JSON on limit breach
        if "Note" in data or "Information" in data:
            msg = data.get("Note") or data.get("Information")
            logger.warning(f"Alpha Vantage rate limit or error: {msg}")
            return {}

        # Trim time series data to last 20 data points — full history
        # is thousands of entries and will overflow the LLM context window
        for key in list(data.keys()):
            if key.startswith("Technical Analysis") or key.startswith("Meta"):
                if isinstance(data[key], dict) and len(data[key]) > 20:
                    trimmed = dict(list(data[key].items())[:20])
                    data[key] = trimmed

        self._cache[cache_key] = (now, data)
        return data

    def get_rsi(self, ticker: str, period: int = 14) -> dict:
        """
        Relative Strength Index — momentum oscillator (0-100).

        RSI > 70 = overbought (mean reversion short candidate)
        RSI < 30 = oversold (mean reversion long candidate)
        RSI divergence from price = strong reversal signal

        The Quant Agent uses RSI primarily for mean reversion setups
        and to confirm/deny momentum signals from MACD.
        """
        return self._fetch({
            "function": "RSI",
            "symbol": ticker,
            "interval": "daily",
            "time_period": str(period),
            "series_type": "close",
        })

    def get_macd(self, ticker: str) -> dict:
        """
        MACD (Moving Average Convergence Divergence).

        Bullish crossover: MACD line crosses above signal line
        Bearish crossover: MACD line crosses below signal line
        Histogram expansion: trend strengthening
        Histogram contraction: trend weakening

        The Quant Agent uses MACD for trend-following signals.
        """
        return self._fetch({
            "function": "MACD",
            "symbol": ticker,
            "interval": "daily",
            "series_type": "close",
        })

    def get_bollinger_bands(self, ticker: str, period: int = 20) -> dict:
        """
        Bollinger Bands — volatility envelope around SMA.

        Price at upper band = stretched (potential reversion or breakout)
        Price at lower band = compressed (potential bounce or breakdown)
        Band squeeze (narrow width) = volatility expansion imminent

        The Quant Agent uses bandwidth for volatility regime detection
        and band touches for mean reversion entries.
        """
        return self._fetch({
            "function": "BBANDS",
            "symbol": ticker,
            "interval": "daily",
            "time_period": str(period),
            "series_type": "close",
        })

    def get_sma(self, ticker: str, period: int = 50) -> dict:
        """
        Simple Moving Average.

        SMA50 vs SMA200 cross = golden cross (bullish) / death cross (bearish).
        Price vs SMA = trend positioning.
        """
        return self._fetch({
            "function": "SMA",
            "symbol": ticker,
            "interval": "daily",
            "time_period": str(period),
            "series_type": "close",
        })

    def get_ema(self, ticker: str, period: int = 20) -> dict:
        """
        Exponential Moving Average — reacts faster than SMA.
        Used for shorter-term trend signals.
        """
        return self._fetch({
            "function": "EMA",
            "symbol": ticker,
            "interval": "daily",
            "time_period": str(period),
            "series_type": "close",
        })
