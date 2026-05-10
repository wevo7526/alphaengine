"""
Portfolio Optimization — Black-Litterman and Mean-Variance.

Converts agent signals (direction + conviction) into optimal portfolio weights
accounting for correlations between positions.
Pure math via numpy/scipy. No LLM calls.
"""

import numpy as np
import math
from scipy.optimize import minimize
import logging

from data.market_client import MarketDataClient
from quant import limits as _limits

logger = logging.getLogger(__name__)

_market = MarketDataClient()


def _regularize_cov(cov: np.ndarray) -> tuple[np.ndarray, dict]:
    """
    Tikhonov regularization for ill-conditioned covariance matrices.

    When cond(Sigma) > OPTIMIZER_RIDGE_TRIGGER_COND (default 1e10), inverting
    Sigma in Black-Litterman or solving the SLSQP quadratic with it produces
    numerically meaningless weights. We add `lambda * trace(Sigma)/n * I` to
    the diagonal — a Ledoit-Wolf-style shrinkage toward the identity scaled
    by the average variance, which raises the smallest eigenvalues without
    distorting relative risk much. Returns the (possibly regularized) matrix
    plus a diagnostic dict for transparency.
    """
    n = cov.shape[0]
    info: dict = {"applied": False}
    try:
        cond = float(np.linalg.cond(cov))
    except Exception:
        cond = float("inf")
    info["condition_number_before"] = cond if math.isfinite(cond) else None

    if not math.isfinite(cond) or cond > _limits.OPTIMIZER_RIDGE_TRIGGER_COND:
        avg_var = float(np.trace(cov) / n) if n > 0 else 0.0
        # Use a small absolute floor when avg_var is ~0, so a degenerate
        # all-zero diagonal still gets nudged off the rank-deficient corner.
        ridge_scale = max(avg_var, 1e-8)
        ridge = _limits.OPTIMIZER_RIDGE_LAMBDA * ridge_scale
        cov_reg = cov + ridge * np.eye(n)
        try:
            cond_after = float(np.linalg.cond(cov_reg))
        except Exception:
            cond_after = float("inf")
        info.update({
            "applied": True,
            "ridge_lambda": _limits.OPTIMIZER_RIDGE_LAMBDA,
            "ridge_added_to_diag": round(ridge, 8),
            "condition_number_after": cond_after if math.isfinite(cond_after) else None,
        })
        return cov_reg, info
    return cov, info

DIRECTION_MAP = {
    "strong_bearish": -1.0, "bearish": -0.5, "neutral": 0.0,
    "bullish": 0.5, "strong_bullish": 1.0,
}


def _clean(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def mean_variance_optimize(
    expected_returns: dict[str, float],
    cov_matrix: dict,
    target_vol: float = 0.15,
    long_only: bool = True,
    current_weights: dict[str, float] | None = None,
    transaction_cost_bps: float = 10.0,
    max_position_size: float = 0.05,
    dollar_neutral: bool = False,
    beta_neutral: bool = False,
    asset_betas: dict[str, float] | None = None,
    gross_leverage: float = 1.0,
) -> dict:
    """
    Classical Markowitz mean-variance optimization with optional L/S
    market-neutral construction.

    Default mode (long_only=True): weights sum to 1, bounded [0, cap].
    Maximizes Sharpe. Transaction cost penalty when current_weights given.

    L/S mode (long_only=False AND (dollar_neutral OR beta_neutral)):
        Reformulates variables as w = w_long - w_short, both ≥ 0, with explicit
        gross leverage constraint sum(w_long + w_short) = gross_leverage.

        - dollar_neutral=True: sum(w_long) = sum(w_short)  ⇔  sum(w) = 0
        - beta_neutral=True: sum(w · β) = 0
        - asset_betas: per-ticker β to the market; required for beta_neutral.
          Missing β falls back to dollar_neutral with a logged warning.

    Returns method='long_short_market_neutral' in L/S mode so consumers can
    branch on it. The realized gross, net, and portfolio beta are surfaced
    so a PM can verify the neutrality constraint actually bound.

    Reasoning: SLSQP can't handle abs() in constraints directly. The long/
    short split (Markowitz 1959, Jacobs/Levy 1993) is the textbook way to
    encode |w| limits in a smooth QP — no penalty terms, no rounding.
    """
    tickers = cov_matrix.get("tickers", [])
    matrix = cov_matrix.get("matrix", [])
    if not tickers or not matrix:
        return {"error": "No covariance data"}

    n = len(tickers)
    mu = np.array([expected_returns.get(t, 0) for t in tickers], dtype=float)
    cov = np.array(matrix)
    cov = np.where(cov == None, 0, cov).astype(float)
    cov, ridge_info = _regularize_cov(cov)
    w_current = np.array([(current_weights or {}).get(t, 0.0) for t in tickers], dtype=float)
    tc = transaction_cost_bps / 10000.0
    cap = max(0.0, min(1.0, max_position_size))

    # ---- L/S market-neutral path ----------------------------------------
    use_ls_path = (not long_only) and (dollar_neutral or beta_neutral)
    if use_ls_path:
        # Resolve betas; fall back gracefully if missing
        betas_arr: np.ndarray | None = None
        beta_neutral_active = bool(beta_neutral)
        if beta_neutral:
            if asset_betas:
                betas_arr = np.array(
                    [float(asset_betas.get(t, float("nan")) or float("nan")) for t in tickers],
                    dtype=float,
                )
                if np.isnan(betas_arr).any():
                    missing = [tickers[i] for i in range(n) if math.isnan(float(betas_arr[i]))]
                    logger.warning(
                        f"beta_neutral=True but missing betas for {missing} — "
                        f"falling back to dollar_neutral only"
                    )
                    beta_neutral_active = False
                    betas_arr = None
            else:
                logger.warning(
                    "beta_neutral=True but asset_betas not provided — "
                    "falling back to dollar_neutral only"
                )
                beta_neutral_active = False

        gross = max(0.01, float(gross_leverage))

        def _w_from_x(x: np.ndarray) -> np.ndarray:
            return x[:n] - x[n:]

        def neg_sharpe_ls(x: np.ndarray) -> float:
            w = _w_from_x(x)
            port_ret = float(mu @ w)
            if current_weights is not None:
                port_ret -= tc * float(np.sum(np.abs(w - w_current)))
            port_var = float(w @ cov @ w)
            if port_var <= 1e-14:
                return 0.0
            return -port_ret / float(np.sqrt(port_var))

        cons_ls: list[dict] = [
            # Gross leverage equality: sum(l + s) = gross
            {"type": "eq", "fun": lambda x: float(np.sum(x) - gross)},
        ]
        if dollar_neutral:
            cons_ls.append(
                {"type": "eq", "fun": lambda x: float(np.sum(_w_from_x(x)))}
            )
        if beta_neutral_active and betas_arr is not None:
            betas_local = betas_arr  # bind to lambda closure
            cons_ls.append(
                {"type": "eq", "fun": lambda x: float(np.dot(betas_local, _w_from_x(x)))}
            )

        bounds_ls = [(0.0, cap) for _ in range(2 * n)]

        # Initialize half-long / half-short equal weight across all names.
        # Splitting evenly is a neutral starting point; SLSQP will redistribute.
        x0 = np.full(2 * n, gross / (2 * n))

        result = minimize(
            neg_sharpe_ls,
            x0,
            method="SLSQP",
            bounds=bounds_ls,
            constraints=cons_ls,
            options={"maxiter": 200, "ftol": 1e-7},
        )

        if not result.success:
            logger.warning(f"L/S optimization failed: {result.message}")
            return {"error": result.message, "method": "long_short_market_neutral"}

        w_opt = _w_from_x(result.x)
        weights = {tickers[i]: _clean(round(float(w_opt[i]), 4)) for i in range(n)}
        port_ret = float(mu @ w_opt)
        port_var = float(w_opt @ cov @ w_opt)
        port_vol = float(np.sqrt(port_var)) if port_var > 0 else 0.0

        gross_realized = float(np.sum(result.x))
        net_realized = float(np.sum(w_opt))
        beta_realized: float | None = (
            float(np.dot(betas_arr, w_opt)) if betas_arr is not None else None
        )
        long_weight = float(np.sum(np.maximum(w_opt, 0.0)))
        short_weight = float(np.sum(np.maximum(-w_opt, 0.0)))

        turnover = float(np.sum(np.abs(w_opt - w_current))) if current_weights is not None else 0.0
        tc_drag = tc * turnover

        return {
            "weights": weights,
            "expected_return_pct": _clean(round(port_ret * 100, 2)),
            "expected_vol_pct": _clean(round(port_vol * 100, 2)),
            "sharpe": _clean(round(port_ret / port_vol, 3)) if port_vol > 0 else None,
            "turnover_pct": _clean(round(turnover * 100, 2)),
            "tx_cost_drag_pct": _clean(round(tc_drag * 100, 4)),
            "max_position_cap_pct": round(cap * 100, 2),
            "gross_leverage_target": round(gross, 4),
            "gross_leverage_realized": round(gross_realized, 4),
            "net_exposure_realized": round(net_realized, 4),
            "long_exposure": round(long_weight, 4),
            "short_exposure": round(short_weight, 4),
            "portfolio_beta_realized": (
                round(beta_realized, 4) if beta_realized is not None else None
            ),
            "dollar_neutral": bool(dollar_neutral),
            "beta_neutral": bool(beta_neutral_active),
            "beta_neutral_requested": bool(beta_neutral),
            "ridge_regularization": ridge_info,
            "method": "long_short_market_neutral",
        }

    # ---- Original (long-only or unconstrained directional) path ---------
    def neg_sharpe(w):
        port_ret = mu @ w
        if current_weights is not None:
            # Linear turnover penalty — proxy for round-trip transaction costs
            port_ret -= tc * float(np.sum(np.abs(w - w_current)))
        port_vol = np.sqrt(w @ cov @ w)
        if port_vol == 0:
            return 0
        return -port_ret / port_vol

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]

    if long_only:
        bounds = [(0, cap) for _ in range(n)]
    else:
        bounds = [(-cap, cap) for _ in range(n)]

    w0 = np.ones(n) / n

    result = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints)

    if not result.success:
        logger.warning(f"Optimization failed: {result.message}")
        return {"error": result.message}

    weights = {tickers[i]: _clean(round(float(result.x[i]), 4)) for i in range(n)}
    port_ret = float(mu @ result.x)
    port_vol = float(np.sqrt(result.x @ cov @ result.x))
    turnover = float(np.sum(np.abs(result.x - w_current))) if current_weights is not None else 0.0
    tc_drag = tc * turnover

    return {
        "weights": weights,
        "expected_return_pct": _clean(round(port_ret * 100, 2)),
        "expected_vol_pct": _clean(round(port_vol * 100, 2)),
        "sharpe": _clean(round(port_ret / port_vol, 3)) if port_vol > 0 else None,
        "turnover_pct": _clean(round(turnover * 100, 2)),
        "tx_cost_drag_pct": _clean(round(tc_drag * 100, 4)),
        "max_position_cap_pct": round(cap * 100, 2),
        "ridge_regularization": ridge_info,
        "method": "mean_variance",
    }


def black_litterman(
    tickers: list[str],
    cov_matrix: dict,
    views: dict[str, float],
    view_confidences: dict[str, float],
    risk_aversion: float = 2.5,
    tau: float = 0.05,
    max_position_size: float = 0.05,
    market_caps: dict[str, float] | None = None,
) -> dict:
    """
    Black-Litterman model.
    views = {ticker: expected_excess_return} from agent signals
    view_confidences = {ticker: confidence 0-1} from conviction
    market_caps = {ticker: market_cap_in_USD} — used to compute the
        equilibrium prior. If omitted, falls back to equal weights (which
        is theoretically incorrect but avoids breaking callers that don't
        have cap data; the result is flagged via market_proxy="equal_weight").
    """
    matrix = cov_matrix.get("matrix", [])
    if not tickers or not matrix:
        return {"error": "No covariance data"}

    n = len(tickers)
    Sigma = np.array(matrix)
    Sigma = np.where(Sigma == None, 0, Sigma).astype(float)
    Sigma, ridge_info = _regularize_cov(Sigma)

    # Market cap weights — proper BL prior. Fall back to equal weight only
    # when caps are missing or all zero (can happen for thinly-covered tickers).
    market_proxy = "market_cap"
    if market_caps:
        caps = np.array([float(market_caps.get(t, 0.0) or 0.0) for t in tickers])
        cap_sum = float(caps.sum())
        if cap_sum > 0:
            w_market = caps / cap_sum
        else:
            w_market = np.ones(n) / n
            market_proxy = "equal_weight_fallback"
    else:
        w_market = np.ones(n) / n
        market_proxy = "equal_weight"

    # Equilibrium returns: pi = risk_aversion * Sigma @ w_market
    pi = risk_aversion * Sigma @ w_market

    # Views
    view_tickers = [t for t in tickers if t in views]
    if not view_tickers:
        # No views — return equilibrium
        weights = {tickers[i]: round(float(w_market[i]), 4) for i in range(n)}
        return {
            "weights": weights,
            "method": "equilibrium",
            "note": "No agent views available",
            "market_proxy": market_proxy,
            "ridge_regularization": ridge_info,
        }

    k = len(view_tickers)
    P = np.zeros((k, n))  # Pick matrix
    Q = np.zeros(k)  # View vector
    omega_diag = np.zeros(k)  # View uncertainty

    # View confidence -> Omega (view uncertainty) mapping.
    # Original code used omega = (1 - conf) / conf * tau * Sigma[idx, idx],
    # which collapses to Omega ≈ tau*Sigma at conf=0.5 — drowning every
    # mid-conviction view under prior uncertainty. That made the system
    # treat 75-conviction signals like 50-conviction signals.
    #
    # Fixed mapping: a confidence floor of 0.5 (we never trust conviction
    # below that) maps via squared falloff so a conviction of 1.0 yields
    # very tight Omega (strong view), and a conviction of 0.5 yields Omega
    # equal to tau * variance (i.e., the prior dominates only at the floor,
    # not at every middle value). Matches Idzorek's (2002) confidence-based
    # weighting in spirit.
    for j, t in enumerate(view_tickers):
        idx = tickers.index(t)
        P[j, idx] = 1
        Q[j] = views[t]
        raw_conf = float(view_confidences.get(t, 0.5))
        conf = max(0.5, min(1.0, raw_conf))   # floor at 0.5
        # Falloff: at conf=1.0, omega ≈ 0.05 * tau * sigma (near-certain);
        #         at conf=0.5, omega ≈ tau * sigma (prior weight equals view).
        falloff = ((1.0 - conf) / 0.5) ** 2 + 0.05
        omega_diag[j] = max(1e-8, falloff * tau * float(Sigma[idx, idx]))

    Omega = np.diag(omega_diag)

    # Posterior returns
    tau_sigma_inv = np.linalg.inv(tau * Sigma)
    p_omega_p = P.T @ np.linalg.inv(Omega) @ P
    posterior_cov_inv = tau_sigma_inv + p_omega_p
    posterior_cov = np.linalg.inv(posterior_cov_inv)

    mu_bl = posterior_cov @ (tau_sigma_inv @ pi + P.T @ np.linalg.inv(Omega) @ Q)

    # Optimize with posterior
    def neg_utility(w):
        return -(w @ mu_bl - (risk_aversion / 2) * w @ Sigma @ w)

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
    cap = max(0.0, min(1.0, max_position_size))
    bounds = [(0, cap) for _ in range(n)]
    w0 = np.ones(n) / n

    result = minimize(neg_utility, w0, method="SLSQP", bounds=bounds, constraints=constraints)

    if not result.success:
        return {"error": result.message}

    weights = {tickers[i]: _clean(round(float(result.x[i]), 4)) for i in range(n)}
    port_ret = float(mu_bl @ result.x)
    port_vol = float(np.sqrt(result.x @ Sigma @ result.x))

    return {
        "weights": weights,
        "expected_return_pct": _clean(round(port_ret * 100, 2)),
        "expected_vol_pct": _clean(round(port_vol * 100, 2)),
        "sharpe": _clean(round(port_ret / port_vol, 3)) if port_vol > 0 else None,
        "posterior_returns": {tickers[i]: _clean(round(float(mu_bl[i]) * 100, 2)) for i in range(n)},
        "market_proxy": market_proxy,
        "ridge_regularization": ridge_info,
        "method": "black_litterman",
    }


def signals_to_views(
    trade_ideas: list[dict],
    max_expected_return: float = 0.20,
) -> tuple[dict[str, float], dict[str, float]]:
    """
    Convert agent trade ideas to Black-Litterman views.
    direction * conviction * max_expected_return = expected excess return.
    """
    views = {}
    confidences = {}

    for idea in trade_ideas:
        ticker = idea.get("ticker", "")
        direction = idea.get("direction", "neutral")
        conviction = idea.get("conviction", 50)

        dir_numeric = DIRECTION_MAP.get(direction, 0)
        expected_return = dir_numeric * (conviction / 100) * max_expected_return
        confidence = conviction / 100

        views[ticker] = expected_return
        confidences[ticker] = confidence

    return views, confidences


def generate_rebalance_trades(
    current_weights: dict[str, float],
    target_weights: dict[str, float],
    portfolio_value: float = 100000,
    min_trade_size: float = 500,
) -> list[dict]:
    """Compute trades to move from current to target weights."""
    all_tickers = set(list(current_weights.keys()) + list(target_weights.keys()))
    trades = []

    for ticker in all_tickers:
        current = current_weights.get(ticker, 0)
        target = target_weights.get(ticker, 0)
        delta = target - current
        dollar_amount = abs(delta * portfolio_value)

        if dollar_amount < min_trade_size:
            continue

        trades.append({
            "ticker": ticker,
            "action": "BUY" if delta > 0 else "SELL",
            "current_weight": round(current * 100, 2),
            "target_weight": round(target * 100, 2),
            "delta_weight": round(delta * 100, 2),
            "dollar_amount": round(dollar_amount, 2),
        })

    trades.sort(key=lambda x: abs(x["dollar_amount"]), reverse=True)
    return trades
