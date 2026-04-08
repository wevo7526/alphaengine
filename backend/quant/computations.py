"""
Quant computation modules — pure math, no LLM.

These produce the computed outputs that differentiate Alpha Engine from ChatGPT:
correlation matrices, drawdown analysis, VaR, volatility metrics.
All computed from live market data via the data clients.
"""

import numpy as np
from datetime import datetime, timedelta
import logging

from data.market_client import MarketDataClient
from data.fred_client import FREDDataClient

logger = logging.getLogger(__name__)

_market = MarketDataClient()
_fred = FREDDataClient()


def compute_correlation_matrix(tickers: list[str], period: str = "3mo") -> dict:
    """
    Compute pairwise return correlation matrix for a set of tickers.
    Returns a matrix + labels for heatmap rendering.
    """
    if len(tickers) < 2:
        return {"tickers": tickers, "matrix": [[1.0]], "error": "Need 2+ tickers"}

    prices = {}
    for t in tickers:
        history = _market.get_price_history(t, period=period)
        if history:
            prices[t] = [bar["close"] for bar in history]

    valid_tickers = [t for t in tickers if t in prices and len(prices[t]) > 5]
    if len(valid_tickers) < 2:
        return {"tickers": valid_tickers, "matrix": [], "error": "Insufficient data"}

    # Align lengths
    min_len = min(len(prices[t]) for t in valid_tickers)
    returns = {}
    for t in valid_tickers:
        p = prices[t][-min_len:]
        r = [(p[i] - p[i - 1]) / p[i - 1] for i in range(1, len(p))]
        returns[t] = r

    n = len(valid_tickers)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            ri = np.array(returns[valid_tickers[i]])
            rj = np.array(returns[valid_tickers[j]])
            corr = float(np.corrcoef(ri, rj)[0, 1])
            matrix[i][j] = round(corr, 3)

    return {"tickers": valid_tickers, "matrix": matrix}


def compute_drawdown(ticker: str, period: str = "6mo") -> dict:
    """
    Compute drawdown series from peak.
    Returns daily drawdown percentages for chart rendering.
    """
    history = _market.get_price_history(ticker, period=period)
    if not history:
        return {"ticker": ticker, "series": [], "max_drawdown": 0}

    closes = [bar["close"] for bar in history]
    dates = [bar["date"] for bar in history]

    peak = closes[0]
    series = []
    max_dd = 0
    for i, c in enumerate(closes):
        if c > peak:
            peak = c
        dd = (c - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd
        series.append({"date": dates[i], "drawdown": round(dd, 2)})

    return {
        "ticker": ticker,
        "series": series,
        "max_drawdown": round(max_dd, 2),
        "current_drawdown": series[-1]["drawdown"] if series else 0,
    }


def compute_volatility_metrics(ticker: str, period: str = "6mo") -> dict:
    """
    Compute realized vol, Sharpe-like ratio, and basic risk stats.
    """
    history = _market.get_price_history(ticker, period=period)
    if not history or len(history) < 10:
        return {"ticker": ticker, "error": "Insufficient data"}

    closes = [bar["close"] for bar in history]
    daily_returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    arr = np.array(daily_returns)
    realized_vol = float(np.std(arr) * np.sqrt(252) * 100)
    mean_return = float(np.mean(arr) * 252 * 100)
    sharpe = mean_return / realized_vol if realized_vol > 0 else 0
    skew = float(((arr - arr.mean()) ** 3).mean() / (arr.std() ** 3)) if arr.std() > 0 else 0
    max_daily_loss = float(arr.min() * 100)
    max_daily_gain = float(arr.max() * 100)

    # Historical VaR (95%)
    var_95 = float(np.percentile(arr, 5) * 100)

    return {
        "ticker": ticker,
        "realized_vol_annualized": round(realized_vol, 2),
        "annualized_return": round(mean_return, 2),
        "sharpe_ratio": round(sharpe, 2),
        "skewness": round(skew, 2),
        "var_95_daily": round(var_95, 2),
        "max_daily_loss": round(max_daily_loss, 2),
        "max_daily_gain": round(max_daily_gain, 2),
        "observations": len(daily_returns),
    }


def get_macro_time_series() -> dict:
    """
    Get time series data for macro charts: yield curve, VIX, credit spreads.
    Returns arrays ready for frontend chart rendering.
    """
    series = {}

    for series_id, label in [
        ("T10Y2Y", "yield_curve"),
        ("VIXCLS", "vix"),
        ("BAMLH0A0HYM2", "credit_spreads"),
        ("DFF", "fed_funds"),
    ]:
        try:
            data = _fred.get_series_history(series_id, lookback_days=180)
            series[label] = data
        except Exception as e:
            logger.warning(f"Failed to fetch {series_id}: {e}")
            series[label] = []

    return series
