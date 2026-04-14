"""
Risk Management Framework — pure math, zero LLM coupling.

EWMA covariance, portfolio VaR/CVaR, sector limits, correlation-adjusted
sizing, drawdown circuit breaker, marginal VaR.
"""

import numpy as np
import math
import logging

logger = logging.getLogger(__name__)


def _clean(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def compute_ewma_covariance(returns_dict: dict[str, list[float]], halflife: int = 63) -> dict:
    """
    Exponentially Weighted Moving Average covariance matrix.
    halflife=63 (~1 quarter) weights recent data more heavily.
    Returns {tickers, matrix} for frontend heatmap rendering.
    """
    tickers = list(returns_dict.keys())
    if len(tickers) < 2:
        return {"tickers": tickers, "matrix": [[1.0]], "error": "Need 2+ assets"}

    # Align to minimum length
    min_len = min(len(r) for r in returns_dict.values())
    if min_len < 10:
        return {"tickers": tickers, "matrix": [], "error": "Insufficient data"}

    data = np.array([returns_dict[t][-min_len:] for t in tickers])  # N x T
    n, T = data.shape

    # EWMA weights: lambda = 0.5^(1/halflife)
    lam = 0.5 ** (1 / halflife)
    weights = np.array([(1 - lam) * lam ** i for i in range(T - 1, -1, -1)])
    weights /= weights.sum()

    # Weighted covariance
    means = (data * weights).sum(axis=1, keepdims=True)
    centered = data - means
    cov = np.zeros((n, n))
    for t_idx in range(T):
        cov += weights[t_idx] * np.outer(centered[:, t_idx], centered[:, t_idx])

    # Annualize
    cov *= 252

    matrix = [[_clean(round(float(cov[i, j]), 6)) for j in range(n)] for i in range(n)]
    return {"tickers": tickers, "matrix": matrix}


def compute_portfolio_var(
    weights: dict[str, float],
    cov_matrix: dict,
    portfolio_value: float = 100000,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> dict:
    """
    Parametric VaR: z * portfolio_vol * sqrt(horizon).
    Returns dollar VaR and percentage VaR.
    """
    tickers = cov_matrix.get("tickers", [])
    matrix = cov_matrix.get("matrix", [])
    if not tickers or not matrix:
        return {"var_pct": None, "var_dollars": None, "error": "No covariance data"}

    w = np.array([weights.get(t, 0) for t in tickers])
    cov = np.array(matrix)

    # Replace None with 0 in cov
    cov = np.where(cov == None, 0, cov).astype(float)

    port_var = float(w @ cov @ w)
    port_vol = np.sqrt(port_var) if port_var > 0 else 0

    z_scores = {0.95: 1.645, 0.99: 2.326}
    z = z_scores.get(confidence, 1.645)

    daily_var_pct = z * port_vol / np.sqrt(252) * np.sqrt(horizon_days)
    var_dollars = daily_var_pct * portfolio_value

    return {
        "var_pct": _clean(round(float(daily_var_pct * 100), 2)),
        "var_dollars": _clean(round(float(var_dollars), 2)),
        "portfolio_vol_annual": _clean(round(float(port_vol * 100), 2)),
        "confidence": confidence,
        "horizon_days": horizon_days,
    }


def compute_portfolio_cvar(
    portfolio_returns: list[float],
    confidence: float = 0.95,
) -> dict:
    """
    Historical CVaR (Expected Shortfall).
    Mean of returns below the VaR threshold.
    """
    if len(portfolio_returns) < 20:
        return {"cvar_pct": None, "error": "Need 20+ observations"}

    arr = np.array(portfolio_returns)
    var_cutoff = np.percentile(arr, (1 - confidence) * 100)
    tail = arr[arr <= var_cutoff]
    cvar = float(np.mean(tail)) if len(tail) > 0 else float(var_cutoff)

    return {
        "cvar_pct": _clean(round(cvar * 100, 2)),
        "var_pct": _clean(round(float(var_cutoff) * 100, 2)),
        "tail_observations": len(tail),
    }


def check_sector_limits(
    positions: dict[str, dict],
    max_sector_pct: float = 0.30,
) -> dict:
    """
    Check sector concentration. positions = {ticker: {sector, weight}}.
    Returns violations and current sector breakdown.
    """
    sector_totals: dict[str, float] = {}
    for ticker, info in positions.items():
        sector = info.get("sector", "Unknown")
        sector_totals[sector] = sector_totals.get(sector, 0) + info.get("weight", 0)

    violations = []
    for sector, total in sector_totals.items():
        if total > max_sector_pct:
            violations.append({
                "sector": sector,
                "current_pct": round(total * 100, 1),
                "limit_pct": round(max_sector_pct * 100, 1),
                "excess_pct": round((total - max_sector_pct) * 100, 1),
            })

    return {
        "sector_breakdown": {k: round(v * 100, 1) for k, v in sector_totals.items()},
        "violations": violations,
        "compliant": len(violations) == 0,
    }


def drawdown_circuit_breaker(current_drawdown_pct: float) -> dict:
    """
    Tiered response to portfolio drawdown.
    DD < 5%: normal. 5-7%: reduce 50%. 7-10%: no new. >10%: liquidate to 50% cash.
    """
    dd = abs(current_drawdown_pct)
    if dd < 5:
        return {"status": "normal", "size_multiplier": 1.0, "action": "Full sizing allowed", "color": "green"}
    elif dd < 7:
        return {"status": "caution", "size_multiplier": 0.5, "action": "Reduce new positions by 50%", "color": "yellow"}
    elif dd < 10:
        return {"status": "warning", "size_multiplier": 0.0, "action": "No new positions, tighten stops", "color": "orange"}
    else:
        return {"status": "critical", "size_multiplier": 0.0, "action": "Liquidate to 50% cash", "color": "red"}


def correlation_adjusted_size(
    base_size: float,
    new_ticker_returns: list[float],
    existing_returns: dict[str, list[float]],
    max_penalty: float = 0.5,
) -> dict:
    """
    Reduce position size when correlated with existing positions.
    Returns adjusted size and the avg correlation.
    """
    if not existing_returns or not new_ticker_returns:
        return {"adjusted_size": base_size, "avg_correlation": 0, "penalty": 0}

    new = np.array(new_ticker_returns)
    correlations = []
    for ticker, rets in existing_returns.items():
        r = np.array(rets)
        min_len = min(len(new), len(r))
        if min_len < 10:
            continue
        corr = float(np.corrcoef(new[-min_len:], r[-min_len:])[0, 1])
        if not math.isnan(corr):
            correlations.append(corr)

    if not correlations:
        return {"adjusted_size": base_size, "avg_correlation": 0, "penalty": 0}

    avg_corr = float(np.mean(correlations))
    penalty = max(0, avg_corr) * max_penalty
    adjusted = base_size * (1 - penalty)

    return {
        "adjusted_size": round(adjusted, 4),
        "avg_correlation": round(avg_corr, 3),
        "penalty": round(penalty, 3),
        "original_size": base_size,
    }
