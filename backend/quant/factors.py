"""
Factor Analysis — Fama-French factor loading, regression, attribution.

Decomposes portfolio returns into systematic (factor) and idiosyncratic (alpha).
Uses Kenneth French Data Library for factor returns.
Pure math via numpy/statsmodels. No LLM calls.
"""

import numpy as np
import math
import logging
import time

logger = logging.getLogger(__name__)

# Try statsmodels for OLS
try:
    import statsmodels.api as sm
    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False
    logger.warning("statsmodels not installed — using numpy OLS fallback")


def _clean(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def _numpy_ols(y: np.ndarray, X: np.ndarray) -> dict:
    """Simple OLS fallback when statsmodels isn't available."""
    X_with_const = np.column_stack([np.ones(len(X)), X])
    try:
        betas = np.linalg.lstsq(X_with_const, y, rcond=None)[0]
        y_hat = X_with_const @ betas
        residuals = y - y_hat
        ss_res = float(np.sum(residuals ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        return {
            "betas": betas.tolist(),
            "r_squared": r_squared,
            "residuals": residuals,
        }
    except Exception:
        return {"betas": [0] * (X.shape[1] + 1), "r_squared": 0, "residuals": np.zeros(len(y))}


def compute_factor_loadings(
    portfolio_returns: list[float],
    market_returns: list[float],
    risk_free_rate: float = 0.04,
) -> dict:
    """
    Simplified factor analysis using market returns as the single factor.
    Returns alpha, beta, R-squared.

    For full FF5+Mom, use compute_multi_factor_loadings().
    """
    min_len = min(len(portfolio_returns), len(market_returns))
    if min_len < 30:
        return {"error": "Need 30+ observations", "alpha": None, "beta": None}

    y = np.array(portfolio_returns[-min_len:])
    x = np.array(market_returns[-min_len:])
    rf_daily = risk_free_rate / 252

    # Excess returns
    y_excess = y - rf_daily
    x_excess = x - rf_daily

    result = _numpy_ols(y_excess, x_excess.reshape(-1, 1))
    alpha_daily = result["betas"][0]
    beta = result["betas"][1]

    return {
        "alpha": _clean(round(float(alpha_daily * 252 * 100), 2)),  # Annualized %
        "alpha_daily": _clean(round(float(alpha_daily), 6)),
        "beta": _clean(round(float(beta), 3)),
        "r_squared": _clean(round(float(result["r_squared"]), 3)),
        "residual_vol": _clean(round(float(np.std(result["residuals"]) * np.sqrt(252) * 100), 2)),
    }


def compute_multi_factor_loadings(
    portfolio_returns: list[float],
    factor_returns: dict[str, list[float]],
    risk_free_rate: float = 0.04,
) -> dict:
    """
    Multi-factor regression (FF5 + Momentum style).
    factor_returns = {"market": [...], "size": [...], "value": [...], ...}
    """
    factor_names = list(factor_returns.keys())
    if not factor_names:
        return {"error": "No factor data"}

    min_len = min(len(portfolio_returns), *[len(v) for v in factor_returns.values()])
    if min_len < 30:
        return {"error": "Need 30+ observations"}

    y = np.array(portfolio_returns[-min_len:])
    rf_daily = risk_free_rate / 252
    y_excess = y - rf_daily

    X = np.column_stack([np.array(factor_returns[f][-min_len:]) for f in factor_names])

    if STATSMODELS_AVAILABLE:
        X_const = sm.add_constant(X)
        model = sm.OLS(y_excess, X_const).fit(cov_type="HAC", cov_kwds={"maxlags": 5})

        betas = {}
        tstats = {}
        for i, name in enumerate(factor_names):
            betas[name] = _clean(round(float(model.params[i + 1]), 4))
            tstats[name] = _clean(round(float(model.tvalues[i + 1]), 2))

        return {
            "alpha": _clean(round(float(model.params[0] * 252 * 100), 2)),
            "alpha_tstat": _clean(round(float(model.tvalues[0]), 2)),
            "alpha_pvalue": _clean(round(float(model.pvalues[0]), 4)),
            "factor_betas": betas,
            "factor_tstats": tstats,
            "r_squared": _clean(round(float(model.rsquared), 3)),
            "adj_r_squared": _clean(round(float(model.rsquared_adj), 3)),
            "residual_vol": _clean(round(float(np.std(model.resid) * np.sqrt(252) * 100), 2)),
        }
    else:
        result = _numpy_ols(y_excess, X)
        betas = {}
        for i, name in enumerate(factor_names):
            betas[name] = _clean(round(float(result["betas"][i + 1]), 4))

        return {
            "alpha": _clean(round(float(result["betas"][0] * 252 * 100), 2)),
            "factor_betas": betas,
            "r_squared": _clean(round(float(result["r_squared"]), 3)),
        }


def performance_attribution(
    portfolio_returns: list[float],
    factor_returns: dict[str, list[float]],
    loadings: dict,
) -> dict:
    """
    Decompose total return into factor contributions + alpha.
    """
    betas = loadings.get("factor_betas", {})
    min_len = min(len(portfolio_returns), *[len(v) for v in factor_returns.values()]) if factor_returns else len(portfolio_returns)

    total_return = float(np.sum(portfolio_returns[-min_len:])) * 100

    contributions = {}
    explained = 0
    for factor_name, beta in betas.items():
        if beta and factor_name in factor_returns:
            factor_total = float(np.sum(factor_returns[factor_name][-min_len:])) * 100
            contribution = (beta or 0) * factor_total
            contributions[factor_name] = _clean(round(contribution, 2))
            explained += contribution

    alpha_contribution = total_return - explained

    return {
        "total_return_pct": _clean(round(total_return, 2)),
        "factor_contributions": contributions,
        "alpha_contribution": _clean(round(alpha_contribution, 2)),
        "pct_explained_by_factors": _clean(round(explained / total_return * 100, 1)) if total_return != 0 else 0,
    }


def compute_rolling_factor_exposure(
    portfolio_returns: list[float],
    market_returns: list[float],
    window: int = 60,
    risk_free_rate: float = 0.04,
) -> list[dict]:
    """
    Rolling factor betas over a sliding window.
    Shows how factor exposures evolve over time.
    Returns list of {index, alpha, beta, r_squared}.
    """
    min_len = min(len(portfolio_returns), len(market_returns))
    if min_len < window + 10:
        return []

    y = np.array(portfolio_returns[-min_len:])
    x = np.array(market_returns[-min_len:])
    rf_daily = risk_free_rate / 252

    results = []
    for i in range(window, min_len):
        y_chunk = y[i - window:i] - rf_daily
        x_chunk = x[i - window:i] - rf_daily

        ols = _numpy_ols(y_chunk, x_chunk.reshape(-1, 1))
        alpha_ann = float(ols["betas"][0] * 252 * 100)
        beta = float(ols["betas"][1])

        results.append({
            "index": i,
            "alpha": _clean(round(alpha_ann, 2)),
            "beta": _clean(round(beta, 3)),
            "r_squared": _clean(round(float(ols["r_squared"]), 3)),
        })

    return results
