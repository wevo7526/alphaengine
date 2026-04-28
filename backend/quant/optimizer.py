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

logger = logging.getLogger(__name__)

_market = MarketDataClient()

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
) -> dict:
    """
    Classical Markowitz mean-variance optimization.

    Maximizes Sharpe ratio subject to weights summing to 1, bounded per-name
    by `max_position_size` (default 5% — matches the risk gate so the
    optimizer can't suggest weights the gate will reject downstream).

    Transaction cost penalty: when `current_weights` is supplied, the
    objective deducts `transaction_cost_bps * sum(|delta_w|)` from expected
    return. This kills the classic MV pathology where a tiny estimated-return
    differential triggers a complete rebalance — a real fund's turnover would
    bleed all the alpha in commissions.
    """
    tickers = cov_matrix.get("tickers", [])
    matrix = cov_matrix.get("matrix", [])
    if not tickers or not matrix:
        return {"error": "No covariance data"}

    n = len(tickers)
    mu = np.array([expected_returns.get(t, 0) for t in tickers])
    cov = np.array(matrix)
    cov = np.where(cov == None, 0, cov).astype(float)
    w_current = np.array([(current_weights or {}).get(t, 0.0) for t in tickers])
    tc = transaction_cost_bps / 10000.0

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

    cap = max(0.0, min(1.0, max_position_size))
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
) -> dict:
    """
    Black-Litterman model.
    views = {ticker: expected_excess_return} from agent signals
    view_confidences = {ticker: confidence 0-1} from conviction
    """
    matrix = cov_matrix.get("matrix", [])
    if not tickers or not matrix:
        return {"error": "No covariance data"}

    n = len(tickers)
    Sigma = np.array(matrix)
    Sigma = np.where(Sigma == None, 0, Sigma).astype(float)

    # Market cap weights (equal weight as proxy if no market cap data)
    w_market = np.ones(n) / n

    # Equilibrium returns: pi = risk_aversion * Sigma @ w_market
    pi = risk_aversion * Sigma @ w_market

    # Views
    view_tickers = [t for t in tickers if t in views]
    if not view_tickers:
        # No views — return equilibrium
        weights = {tickers[i]: round(float(w_market[i]), 4) for i in range(n)}
        return {"weights": weights, "method": "equilibrium", "note": "No agent views available"}

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
