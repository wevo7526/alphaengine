"""
Performance Analyzer — all standard quant performance metrics.

Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor,
information ratio, beta, alpha, VaR, CVaR, rolling Sharpe.
All vectorized with numpy. No LLM calls.
"""

import numpy as np
import math
import logging

logger = logging.getLogger(__name__)


def _clean(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def sharpe_ratio(returns: list[float], risk_free_rate: float = 0.04) -> float | None:
    """(mean_excess_return / std_return) * sqrt(252)"""
    if len(returns) < 30:
        return None
    arr = np.array(returns)
    rf_daily = risk_free_rate / 252
    excess = arr - rf_daily
    std = float(np.std(excess, ddof=1))
    if std == 0:
        return None
    return _clean(round(float(np.mean(excess) / std * np.sqrt(252)), 3))


def sortino_ratio(returns: list[float], risk_free_rate: float = 0.04) -> float | None:
    """(mean_excess_return / downside_std) * sqrt(252)"""
    if len(returns) < 30:
        return None
    arr = np.array(returns)
    rf_daily = risk_free_rate / 252
    excess = arr - rf_daily
    downside = excess[excess < 0]
    if len(downside) < 5:
        return None
    downside_std = float(np.std(downside, ddof=1))
    if downside_std == 0:
        return None
    return _clean(round(float(np.mean(excess) / downside_std * np.sqrt(252)), 3))


def max_drawdown(equity_curve: list[float]) -> dict:
    """
    Returns max_dd_pct, duration_days, peak_idx, trough_idx.
    """
    if len(equity_curve) < 2:
        return {"max_dd_pct": 0, "duration_days": 0}

    arr = np.array(equity_curve)
    peak = arr[0]
    max_dd = 0
    peak_idx = 0
    trough_idx = 0
    current_peak_idx = 0

    for i in range(1, len(arr)):
        if arr[i] > peak:
            peak = arr[i]
            current_peak_idx = i
        dd = (arr[i] - peak) / peak
        if dd < max_dd:
            max_dd = dd
            peak_idx = current_peak_idx
            trough_idx = i

    return {
        "max_dd_pct": _clean(round(float(max_dd * 100), 2)),
        "duration_days": trough_idx - peak_idx,
        "peak_idx": peak_idx,
        "trough_idx": trough_idx,
    }


def drawdown_series(equity_curve: list[float]) -> list[float]:
    """Running drawdown at each point."""
    if not equity_curve:
        return []
    arr = np.array(equity_curve)
    running_max = np.maximum.accumulate(arr)
    dd = (arr - running_max) / running_max
    return [_clean(round(float(d) * 100, 2)) for d in dd]


def calmar_ratio(returns: list[float], max_dd_pct: float) -> float | None:
    """annualized_return / abs(max_drawdown)"""
    if len(returns) < 30 or max_dd_pct == 0:
        return None
    ann_return = float(np.mean(returns)) * 252 * 100
    return _clean(round(ann_return / abs(max_dd_pct), 3))


def win_rate(trades: list[dict]) -> float | None:
    """Percentage of trades with positive P&L."""
    if not trades:
        return None
    winners = sum(1 for t in trades if (t.get("pnl_pct") or 0) > 0)
    return round(winners / len(trades) * 100, 1)


def profit_factor(trades: list[dict]) -> float | None:
    """sum(winning_pnl) / abs(sum(losing_pnl))"""
    if not trades:
        return None
    wins = sum(t.get("pnl_pct", 0) for t in trades if (t.get("pnl_pct") or 0) > 0)
    losses = abs(sum(t.get("pnl_pct", 0) for t in trades if (t.get("pnl_pct") or 0) < 0))
    if losses == 0:
        return None
    return _clean(round(wins / losses, 2))


def information_ratio(
    returns: list[float], benchmark_returns: list[float]
) -> float | None:
    """(mean(excess) / std(excess)) * sqrt(252)"""
    min_len = min(len(returns), len(benchmark_returns))
    if min_len < 30:
        return None
    excess = np.array(returns[-min_len:]) - np.array(benchmark_returns[-min_len:])
    std = float(np.std(excess, ddof=1))
    if std == 0:
        return None
    return _clean(round(float(np.mean(excess) / std * np.sqrt(252)), 3))


def compute_beta(returns: list[float], benchmark_returns: list[float]) -> float | None:
    """cov(portfolio, benchmark) / var(benchmark)"""
    min_len = min(len(returns), len(benchmark_returns))
    if min_len < 30:
        return None
    p = np.array(returns[-min_len:])
    b = np.array(benchmark_returns[-min_len:])
    var_b = float(np.var(b, ddof=1))
    if var_b == 0:
        return None
    cov = float(np.cov(p, b)[0, 1])
    return _clean(round(cov / var_b, 3))


def alpha_jensen(
    returns: list[float], benchmark_returns: list[float], risk_free_rate: float = 0.04
) -> float | None:
    """Annualized Jensen's alpha."""
    beta = compute_beta(returns, benchmark_returns)
    if beta is None:
        return None
    min_len = min(len(returns), len(benchmark_returns))
    rf_daily = risk_free_rate / 252
    mean_p = float(np.mean(returns[-min_len:]))
    mean_b = float(np.mean(benchmark_returns[-min_len:]))
    alpha_daily = mean_p - rf_daily - beta * (mean_b - rf_daily)
    return _clean(round(alpha_daily * 252 * 100, 2))


def value_at_risk(returns: list[float], confidence: float = 0.95) -> float | None:
    """Historical VaR."""
    if len(returns) < 20:
        return None
    return _clean(round(float(np.percentile(returns, (1 - confidence) * 100)) * 100, 2))


def conditional_var(returns: list[float], confidence: float = 0.95) -> float | None:
    """CVaR / Expected Shortfall."""
    if len(returns) < 20:
        return None
    arr = np.array(returns)
    cutoff = np.percentile(arr, (1 - confidence) * 100)
    tail = arr[arr <= cutoff]
    if len(tail) == 0:
        return _clean(round(float(cutoff) * 100, 2))
    return _clean(round(float(np.mean(tail)) * 100, 2))


def rolling_sharpe(returns: list[float], window: int = 63, risk_free_rate: float = 0.04) -> list[dict]:
    """63-day rolling Sharpe for visualization."""
    if len(returns) < window:
        return []
    arr = np.array(returns)
    rf_daily = risk_free_rate / 252
    result = []
    for i in range(window, len(arr)):
        chunk = arr[i - window:i] - rf_daily
        std = float(np.std(chunk, ddof=1))
        sr = float(np.mean(chunk) / std * np.sqrt(252)) if std > 0 else 0
        result.append({"index": i, "sharpe": _clean(round(sr, 3))})
    return result


def full_performance_report(
    equity_curve: list[float],
    returns: list[float],
    trades: list[dict],
    benchmark_returns: list[float] | None = None,
    risk_free_rate: float = 0.04,
) -> dict:
    """Compute all metrics in one call."""
    dd = max_drawdown(equity_curve)

    report = {
        "sharpe_ratio": sharpe_ratio(returns, risk_free_rate),
        "sortino_ratio": sortino_ratio(returns, risk_free_rate),
        "calmar_ratio": calmar_ratio(returns, dd["max_dd_pct"]) if dd["max_dd_pct"] else None,
        "max_drawdown_pct": dd["max_dd_pct"],
        "max_drawdown_duration_days": dd["duration_days"],
        "total_return_pct": _clean(round((equity_curve[-1] / equity_curve[0] - 1) * 100, 2)) if equity_curve else None,
        "annualized_return_pct": _clean(round(float(np.mean(returns)) * 252 * 100, 2)) if returns else None,
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "total_trades": len(trades),
        "var_95": value_at_risk(returns, 0.95),
        "cvar_95": conditional_var(returns, 0.95),
    }

    if benchmark_returns:
        report["beta"] = compute_beta(returns, benchmark_returns)
        report["alpha"] = alpha_jensen(returns, benchmark_returns, risk_free_rate)
        report["information_ratio"] = information_ratio(returns, benchmark_returns)

    return report
