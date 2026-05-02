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


def build_proxy_factor_returns(period: str = "1y") -> dict[str, list[float]] | None:
    """
    Construct multi-factor return proxies from liquid ETF returns. Closes
    the gap from "code exists, no data source" to "live multi-factor model"
    without depending on the Kenneth French data library.

    Factor proxies (long-short or single-leg where the long leg dominates):
        market        = SPY excess return
        size          = IWM - SPY        (small minus big)
        value         = IWD - IWF        (Russell value minus Russell growth)
        profitability = QUAL - SPY       (MSCI Quality factor minus market)
        low_vol       = USMV - SPY       (low-vol minus market)
        momentum      = MTUM - SPY       (MSCI Momentum minus market)

    Note on naming: this used to label USMV-SPY as "investment" (the
    Fama-French CMA factor). USMV is a low-volatility ETF, which is a
    distinct factor from CMA (conservative-minus-aggressive investment).
    Calling it CMA misrepresented the regression: keeping the same proxy
    but the honest name. A true CMA proxy would require Compustat/CapEx
    data not available from public ETFs.

    Returns None when not enough data — caller falls back to single-factor.
    """
    from data.market_client import MarketDataClient
    mc = MarketDataClient()
    tickers = ["SPY", "IWM", "IWD", "IWF", "QUAL", "USMV", "MTUM"]
    series: dict[str, list[float]] = {}
    for tk in tickers:
        try:
            bars = mc.get_price_history(tk, period=period)
            if not bars or len(bars) < 30:
                continue
            closes = [b["close"] for b in bars if b.get("close")]
            rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            series[tk] = rets
        except Exception as e:
            logger.debug(f"build_proxy_factor_returns: {tk} fetch failed ({e})")

    if "SPY" not in series:
        return None

    n = min(len(v) for v in series.values())
    spy = np.array(series["SPY"][-n:])

    def _diff(a: str, b: str) -> list[float] | None:
        if a not in series or b not in series:
            return None
        return list(np.array(series[a][-n:]) - np.array(series[b][-n:]))

    factors: dict[str, list[float]] = {"market": list(spy)}
    if "IWM" in series:
        factors["size"] = list(np.array(series["IWM"][-n:]) - spy)
    val = _diff("IWD", "IWF")
    if val is not None:
        factors["value"] = val
    if "QUAL" in series:
        factors["profitability"] = list(np.array(series["QUAL"][-n:]) - spy)
    if "USMV" in series:
        factors["low_vol"] = list(np.array(series["USMV"][-n:]) - spy)
    if "MTUM" in series:
        factors["momentum"] = list(np.array(series["MTUM"][-n:]) - spy)
    return factors


def _resolve_rfr(rfr: float | None) -> float:
    """RFR fetched from FRED 3-month yield (cached). Hardcoded 4% fallback."""
    if rfr is not None:
        return float(rfr)
    try:
        from data.fred_client import FREDDataClient
        return FREDDataClient().get_risk_free_rate()
    except Exception:
        return 0.04


def compute_factor_loadings(
    portfolio_returns: list[float],
    market_returns: list[float],
    risk_free_rate: float | None = None,
) -> dict:
    """
    Simplified factor analysis using market returns as the single factor.
    Returns alpha, beta, R-squared. RFR pulled from FRED if not set.

    For full FF5 + Momentum, use compute_multi_factor_loadings().
    """
    min_len = min(len(portfolio_returns), len(market_returns))
    if min_len < 30:
        return {"error": "Need 30+ observations", "alpha": None, "beta": None}

    rfr = _resolve_rfr(risk_free_rate)
    y = np.array(portfolio_returns[-min_len:])
    x = np.array(market_returns[-min_len:])
    rf_daily = rfr / 252

    # Excess returns
    y_excess = y - rf_daily
    x_excess = x - rf_daily

    if STATSMODELS_AVAILABLE:
        X_const = sm.add_constant(x_excess)
        model = sm.OLS(y_excess, X_const).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
        alpha_daily = float(model.params[0])
        beta = float(model.params[1])
        alpha_pvalue = float(model.pvalues[0])
        alpha_tstat = float(model.tvalues[0])
        residual_vol = float(np.std(model.resid) * np.sqrt(252) * 100)
        r_sq = float(model.rsquared)
    else:
        result = _numpy_ols(y_excess, x_excess.reshape(-1, 1))
        alpha_daily = float(result["betas"][0])
        beta = float(result["betas"][1])
        alpha_pvalue = None
        alpha_tstat = None
        residual_vol = float(np.std(result["residuals"]) * np.sqrt(252) * 100)
        r_sq = float(result["r_squared"])

    return {
        "alpha": _clean(round(alpha_daily * 252 * 100, 2)),  # Annualized %
        "alpha_daily": _clean(round(alpha_daily, 6)),
        "alpha_pvalue": _clean(round(alpha_pvalue, 4)) if alpha_pvalue is not None else None,
        "alpha_tstat": _clean(round(alpha_tstat, 2)) if alpha_tstat is not None else None,
        # 5% significance: only TRUE if statsmodels is available AND p < 0.05
        "alpha_significant_at_5pct": bool(alpha_pvalue is not None and alpha_pvalue < 0.05),
        "beta": _clean(round(beta, 3)),
        "r_squared": _clean(round(r_sq, 3)),
        "residual_vol": _clean(round(residual_vol, 2)),
        "n_observations": min_len,
        "risk_free_rate": round(rfr, 4),
    }


def _compute_vif(X: np.ndarray, factor_names: list[str]) -> dict[str, float]:
    """
    Variance inflation factor for each column of X. VIF_j = 1 / (1 - R_j^2)
    where R_j^2 is the R-squared from regressing factor j on all other factors.

    VIF > 10 (rule of thumb) signals multicollinearity. Several of our
    proxies are constructed as `X - SPY`, so they can share variance with
    "market"; surfacing VIF lets the consumer judge whether the loadings
    are individually identified.
    """
    n_features = X.shape[1]
    vifs: dict[str, float] = {}
    for j in range(n_features):
        y_j = X[:, j]
        X_others = np.delete(X, j, axis=1)
        if X_others.shape[1] == 0:
            vifs[factor_names[j]] = 1.0
            continue
        try:
            X_const = np.column_stack([np.ones(len(y_j)), X_others])
            betas, *_ = np.linalg.lstsq(X_const, y_j, rcond=None)
            y_hat = X_const @ betas
            ss_res = float(np.sum((y_j - y_hat) ** 2))
            ss_tot = float(np.sum((y_j - y_j.mean()) ** 2))
            r_sq = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
            vif = 1.0 / max(1e-9, 1.0 - r_sq) if r_sq < 0.9999 else float("inf")
            vifs[factor_names[j]] = vif if math.isfinite(vif) else float("inf")
        except Exception:
            vifs[factor_names[j]] = float("nan")
    return vifs


def compute_multi_factor_loadings(
    portfolio_returns: list[float],
    factor_returns: dict[str, list[float]],
    risk_free_rate: float | None = None,
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

    rfr = _resolve_rfr(risk_free_rate)
    y = np.array(portfolio_returns[-min_len:])
    rf_daily = rfr / 252
    y_excess = y - rf_daily

    X = np.column_stack([np.array(factor_returns[f][-min_len:]) for f in factor_names])

    # Multicollinearity diagnostic — flag factors with VIF above threshold.
    from quant import limits as _limits
    vifs: dict[str, float] = {}
    high_vif: list[str] = []
    if X.shape[1] >= 2:
        vifs = _compute_vif(X, factor_names)
        high_vif = [f for f, v in vifs.items() if math.isfinite(v) and v > _limits.VIF_MAX_THRESHOLD]

    if STATSMODELS_AVAILABLE:
        X_const = sm.add_constant(X)
        model = sm.OLS(y_excess, X_const).fit(cov_type="HAC", cov_kwds={"maxlags": 5})

        betas = {}
        tstats = {}
        for i, name in enumerate(factor_names):
            betas[name] = _clean(round(float(model.params[i + 1]), 4))
            tstats[name] = _clean(round(float(model.tvalues[i + 1]), 2))

        alpha_pvalue = float(model.pvalues[0])
        return {
            "alpha": _clean(round(float(model.params[0] * 252 * 100), 2)),
            "alpha_tstat": _clean(round(float(model.tvalues[0]), 2)),
            "alpha_pvalue": _clean(round(alpha_pvalue, 4)),
            "alpha_significant_at_5pct": bool(alpha_pvalue < 0.05),
            "factor_betas": betas,
            "factor_tstats": tstats,
            "r_squared": _clean(round(float(model.rsquared), 3)),
            "adj_r_squared": _clean(round(float(model.rsquared_adj), 3)),
            "residual_vol": _clean(round(float(np.std(model.resid) * np.sqrt(252) * 100), 2)),
            "n_observations": int(min_len),
            "model": _model_label(factor_names),
            "vifs": {k: _clean(round(v, 2)) if math.isfinite(v) else None for k, v in vifs.items()},
            "high_vif_factors": high_vif,
            "multicollinearity_flag": bool(high_vif),
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
            "model": _model_label(factor_names),
            "vifs": {k: _clean(round(v, 2)) if math.isfinite(v) else None for k, v in vifs.items()},
            "high_vif_factors": high_vif,
            "multicollinearity_flag": bool(high_vif),
        }


def _model_label(factor_names: list[str]) -> str:
    """
    Honest label for the regression — names what's in the model rather than
    branding it "FF5 + Momentum" when one of the legs is a low-vol proxy
    standing in for the (unavailable) CMA factor.
    """
    core_set = set(factor_names)
    if {"market", "size", "value", "profitability", "low_vol", "momentum"}.issubset(core_set):
        return "FF5-style + Low-Vol + Momentum"
    if {"market", "size", "value", "momentum"}.issubset(core_set):
        return "Carhart 4-factor"
    return f"{len(factor_names)}-factor"


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
    risk_free_rate: float | None = None,
) -> list[dict]:
    """
    Rolling factor betas over a sliding window.
    Shows how factor exposures evolve over time.
    Returns list of {index, alpha, beta, r_squared}.
    """
    min_len = min(len(portfolio_returns), len(market_returns))
    if min_len < window + 10:
        return []

    rfr = _resolve_rfr(risk_free_rate)
    y = np.array(portfolio_returns[-min_len:])
    x = np.array(market_returns[-min_len:])
    rf_daily = rfr / 252

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
