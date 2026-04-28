"""
Risk Management Framework — pure math, zero LLM coupling.

EWMA covariance with Ledoit-Wolf shrinkage, parametric+Cornish-Fisher+
historical-bootstrap VaR, CVaR, sector limits, correlation-adjusted sizing,
drawdown circuit breaker, marginal VaR, liquidity assessment.

All thresholds (max position, sector cap, marginal VaR block, etc.) live in
quant.limits and can be overridden via env vars.
"""

import numpy as np
import math
import logging

from quant import limits as _limits

logger = logging.getLogger(__name__)


def _clean(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def compute_ewma_covariance(
    returns_dict: dict[str, list[float]],
    halflife: int = 63,
    shrinkage: bool = True,
) -> dict:
    """
    EWMA covariance matrix with optional Ledoit-Wolf shrinkage toward a
    constant-correlation target.

    Why shrinkage: with N assets and T observations, sample covariance is
    noisy when N is comparable to T. The unshrunken EWMA matrix can be
    near-singular (high condition number), which makes Black-Litterman
    inversion blow up and produces nonsense optimizer weights. Shrinkage
    pulls the estimate toward a well-conditioned target — Ledoit & Wolf
    (2004) showed the optimal shrinkage intensity has a closed-form solution.

    Returns {tickers, matrix, shrinkage_intensity, condition_number,
             ill_conditioned} for frontend display + downstream sanity checks.
    """
    tickers = list(returns_dict.keys())
    if len(tickers) < 2:
        return {"tickers": tickers, "matrix": [[1.0]], "error": "Need 2+ assets"}

    min_len = min(len(r) for r in returns_dict.values())
    if min_len < 10:
        return {"tickers": tickers, "matrix": [], "error": "Insufficient data"}

    data = np.array([returns_dict[t][-min_len:] for t in tickers])  # N x T
    n, T = data.shape

    # EWMA weights: lambda = 0.5^(1/halflife)
    lam = 0.5 ** (1 / halflife)
    weights = np.array([(1 - lam) * lam ** i for i in range(T - 1, -1, -1)])
    weights /= weights.sum()

    means = (data * weights).sum(axis=1, keepdims=True)
    centered = data - means
    sample = np.zeros((n, n))
    for t_idx in range(T):
        sample += weights[t_idx] * np.outer(centered[:, t_idx], centered[:, t_idx])

    shrinkage_intensity = 0.0
    if shrinkage and n >= 2:
        # Ledoit-Wolf shrinkage toward constant-correlation target F.
        # F preserves sample variances on the diagonal, fills off-diagonals
        # with the average pairwise correlation × sqrt(var_i * var_j).
        var = np.diag(sample)
        std = np.sqrt(np.maximum(var, 1e-12))
        corr = sample / np.outer(std, std)
        np.fill_diagonal(corr, 1.0)
        # Average off-diagonal correlation
        mask = ~np.eye(n, dtype=bool)
        avg_corr = float(np.mean(corr[mask])) if mask.any() else 0.0
        F = avg_corr * np.outer(std, std)
        np.fill_diagonal(F, var)

        # Closed-form intensity (Ledoit-Wolf 2003 simplified, with EWMA weights):
        # numerator: variance of sample covariance estimator
        # denominator: squared distance from sample to target
        diff_centered = centered  # N x T
        pi_hat = 0.0
        for t_idx in range(T):
            outer_t = np.outer(diff_centered[:, t_idx], diff_centered[:, t_idx])
            pi_hat += weights[t_idx] * float(np.sum((outer_t - sample) ** 2))
        gamma_hat = float(np.sum((F - sample) ** 2))
        if gamma_hat > 1e-12:
            kappa = pi_hat / gamma_hat
            shrinkage_intensity = max(0.0, min(1.0, kappa / T))
        else:
            shrinkage_intensity = 0.0

        sample = (1 - shrinkage_intensity) * sample + shrinkage_intensity * F

    # Annualize
    sample *= 252

    # Diagnostic: condition number flags ill-conditioned matrices upstream
    try:
        cond = float(np.linalg.cond(sample))
    except Exception:
        cond = float("inf")
    ill_conditioned = bool(cond > 1e12)

    matrix = [[_clean(round(float(sample[i, j]), 6)) for j in range(n)] for i in range(n)]
    return {
        "tickers": tickers,
        "matrix": matrix,
        "shrinkage_intensity": round(float(shrinkage_intensity), 4),
        "condition_number": _clean(round(cond, 2)) if cond != float("inf") else None,
        "ill_conditioned": ill_conditioned,
    }


def compute_portfolio_var(
    weights: dict[str, float],
    cov_matrix: dict,
    portfolio_value: float = 100000,
    confidence: float = 0.95,
    horizon_days: int = 1,
    portfolio_returns: list[float] | None = None,
    bootstrap_samples: int = 1000,
) -> dict:
    """
    Portfolio VaR with three layers of rigor:

    1. Parametric Gaussian VaR — `z * vol * sqrt(horizon)`. Fast, but assumes
       normal returns and lies about tails when they're fat.

    2. Cornish-Fisher adjustment (when portfolio_returns is supplied) —
       expands the z-score by skewness and kurtosis terms so the VaR
       reflects observed non-normality. Fed Reserve / BCBS standard practice.

    3. Bootstrap confidence interval on the VaR estimate itself — resamples
       portfolio returns with replacement, recomputes percentile VaR, reports
       2.5/97.5 bounds. Tells you how much you should trust the number.

    `portfolio_returns` is a list of historical daily portfolio returns (as
    decimals). If absent, only parametric VaR is returned.
    """
    tickers = cov_matrix.get("tickers", [])
    matrix = cov_matrix.get("matrix", [])
    if not tickers or not matrix:
        return {"var_pct": None, "var_dollars": None, "error": "No covariance data"}

    w = np.array([weights.get(t, 0) for t in tickers])
    cov = np.array(matrix)
    cov = np.nan_to_num(cov.astype(float), nan=0.0)

    port_var_quad = float(w @ cov @ w)
    port_vol_annual = np.sqrt(port_var_quad) if port_var_quad > 0 else 0.0

    z_scores = {0.95: 1.645, 0.99: 2.326}
    z = z_scores.get(confidence, 1.645)

    # 1. Parametric Gaussian VaR
    daily_var_pct = z * port_vol_annual / np.sqrt(252) * np.sqrt(horizon_days)
    var_dollars = daily_var_pct * portfolio_value

    result = {
        "var_pct": _clean(round(float(daily_var_pct * 100), 2)),
        "var_dollars": _clean(round(float(var_dollars), 2)),
        "portfolio_vol_annual": _clean(round(float(port_vol_annual * 100), 2)),
        "confidence": confidence,
        "horizon_days": horizon_days,
        "method": "parametric_gaussian",
    }

    if portfolio_returns and len(portfolio_returns) >= 30:
        arr = np.array([r for r in portfolio_returns if r is not None and not np.isnan(r)])
        n_obs = len(arr)
        result["sample_size"] = n_obs
        result["low_sample"] = bool(n_obs < 60)

        # 2. Cornish-Fisher adjusted VaR
        mean = float(np.mean(arr))
        std = float(np.std(arr, ddof=1)) if n_obs > 1 else 0.0
        if std > 0:
            skew = float(np.mean(((arr - mean) / std) ** 3))
            # Excess kurtosis (subtract 3 to get 0 for normal)
            kurt = float(np.mean(((arr - mean) / std) ** 4) - 3.0)
            # Cornish-Fisher z: original z + skew/kurt corrections
            z_cf = (
                z
                + (z ** 2 - 1) * skew / 6.0
                + (z ** 3 - 3 * z) * kurt / 24.0
                - (2 * z ** 3 - 5 * z) * (skew ** 2) / 36.0
            )
            cf_var_daily = z_cf * std * np.sqrt(horizon_days)
            result["cornish_fisher"] = {
                "var_pct": _clean(round(float(cf_var_daily * 100), 2)),
                "var_dollars": _clean(round(float(cf_var_daily * portfolio_value), 2)),
                "skewness": _clean(round(skew, 3)),
                "excess_kurtosis": _clean(round(kurt, 3)),
                "z_adjusted": _clean(round(float(z_cf), 3)),
            }

        # 3. Bootstrap CI on historical-percentile VaR
        if n_obs >= 30:
            rng = np.random.default_rng(42)  # deterministic for auditability
            tail_pct = (1 - confidence) * 100
            samples = rng.choice(arr, size=(bootstrap_samples, n_obs), replace=True)
            boot_vars = np.percentile(samples, tail_pct, axis=1) * np.sqrt(horizon_days)
            lo, hi = np.percentile(boot_vars, [2.5, 97.5])
            point = float(np.percentile(arr, tail_pct)) * np.sqrt(horizon_days)
            result["historical"] = {
                "var_pct": _clean(round(point * 100, 2)),
                "ci_95_low_pct": _clean(round(float(lo) * 100, 2)),
                "ci_95_high_pct": _clean(round(float(hi) * 100, 2)),
                "bootstrap_samples": bootstrap_samples,
            }

    return result


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
    Tiered response to portfolio drawdown. Thresholds from quant.limits.
    Default: <5% normal, 5-7% reduce 50%, 7-10% no new, >10% liquidate.
    """
    dd = abs(current_drawdown_pct)
    caution = _limits.DRAWDOWN_CAUTION_PCT
    warn = _limits.DRAWDOWN_WARN_PCT
    crit = _limits.DRAWDOWN_CRITICAL_PCT
    if dd < caution:
        return {"status": "normal", "size_multiplier": 1.0, "action": "Full sizing allowed", "color": "green"}
    elif dd < warn:
        return {"status": "caution", "size_multiplier": 0.5, "action": "Reduce new positions by 50%", "color": "yellow"}
    elif dd < crit:
        return {"status": "warning", "size_multiplier": 0.0, "action": "No new positions, tighten stops", "color": "orange"}
    else:
        return {"status": "critical", "size_multiplier": 0.0, "action": "Liquidate to 50% cash", "color": "red"}


def assess_liquidity(
    proposed_notional: float,
    avg_daily_volume_shares: float | None,
    current_price: float | None,
    bid: float | None,
    ask: float | None,
    max_pct_of_adv: float | None = None,
    block_pct_of_adv: float | None = None,
) -> dict:
    """
    Liquidity check for a single proposed trade.

    Three signals:
      1. Position-vs-ADV: how many days of average daily volume does the
         position represent? <0.1 days is fine, 0.1-1 day is sized,
         >1 day is illiquid for our universe (a quant desk would call this
         a "big" position).
      2. Days-to-liquidate: at 25% participation, how many days to exit?
         (proposed_position_shares / (0.25 * ADV_shares))
      3. Bid-ask spread cost: half-spread in basis points as estimated
         round-trip slippage on entry+exit.

    Returns recommendation: "ok" / "warn" / "block" with reasons. The gate
    can hard-block on any participation > block_pct_of_adv.
    """
    if max_pct_of_adv is None:
        max_pct_of_adv = _limits.LIQUIDITY_MAX_PCT_OF_ADV
    if block_pct_of_adv is None:
        block_pct_of_adv = _limits.LIQUIDITY_BLOCK_PCT_OF_ADV

    info: dict = {
        "proposed_notional": round(float(proposed_notional or 0), 2),
        "adv_shares": _clean(avg_daily_volume_shares),
        "current_price": _clean(current_price),
    }

    # Pct of ADV — needs both ADV and price
    pct_adv: float | None = None
    days_to_liquidate: float | None = None
    if avg_daily_volume_shares and current_price and current_price > 0:
        position_shares = proposed_notional / current_price
        adv_dollars = avg_daily_volume_shares * current_price
        if adv_dollars > 0:
            pct_adv = proposed_notional / adv_dollars
        # Days to liquidate at 25% participation
        if avg_daily_volume_shares > 0:
            days_to_liquidate = position_shares / (0.25 * avg_daily_volume_shares)
        info["pct_of_adv"] = round(float(pct_adv), 4) if pct_adv is not None else None
        info["days_to_liquidate"] = round(float(days_to_liquidate), 2) if days_to_liquidate is not None else None
        info["adv_dollars"] = round(float(adv_dollars), 2)

    # Bid-ask spread → half-spread in bps as one-way slippage estimate
    spread_bps: float | None = None
    if bid and ask and bid > 0 and ask > 0 and ask > bid:
        mid = (bid + ask) / 2.0
        spread_bps = ((ask - bid) / mid) * 10000.0
        info["spread_bps"] = round(float(spread_bps), 2)
        info["estimated_round_trip_slippage_bps"] = round(float(spread_bps), 2)

    # Recommendation
    reasons: list[str] = []
    recommendation = "ok"
    if pct_adv is not None:
        if pct_adv > block_pct_of_adv:
            recommendation = "block"
            reasons.append(
                f"Position is {pct_adv*100:.1f}% of average daily volume "
                f"(>{block_pct_of_adv*100:.0f}% threshold) — illiquid"
            )
        elif pct_adv > max_pct_of_adv:
            recommendation = "warn"
            reasons.append(
                f"Position is {pct_adv*100:.1f}% of ADV (>{max_pct_of_adv*100:.0f}%) — "
                f"sizeable for this name"
            )
    if spread_bps is not None and spread_bps > 50:
        if recommendation == "ok":
            recommendation = "warn"
        reasons.append(f"Wide bid-ask: {spread_bps:.0f}bp")

    info["recommendation"] = recommendation
    info["reasons"] = reasons
    return info


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


def compute_marginal_var(
    current_weights: dict[str, float],
    new_ticker: str,
    new_weight: float,
    cov_matrix: dict,
    portfolio_value: float = 100000,
    confidence: float = 0.95,
) -> dict:
    """
    Marginal VaR: change in portfolio VaR from ADDING a new position on top
    of the existing book.

    Critical: existing weights are NOT renormalized when the new weight is
    added. Renormalizing would silently shrink every existing position to
    make room for the new one — that's a rebalance, not an addition. The
    book grows; weights now sum to (existing_sum + new_weight) which is
    exactly what we want to measure.

    A negative marginal VaR is impossible if all assets have positive vol,
    so this should always be non-negative. Diversifying = marginal VaR is
    smaller than the *standalone* VaR of the new position (its vol contribution
    is dampened by negative correlation with the book).
    """
    tickers = cov_matrix.get("tickers", [])
    matrix = cov_matrix.get("matrix", [])
    if not tickers or not matrix:
        return {"marginal_var_pct": None, "error": "No covariance data"}
    if new_ticker not in tickers:
        return {"marginal_var_pct": None, "error": f"{new_ticker} not in covariance matrix"}

    cov = np.array(matrix)
    cov = np.nan_to_num(cov.astype(float), nan=0.0)

    z_scores = {0.95: 1.645, 0.99: 2.326}
    z = z_scores.get(confidence, 1.645)

    # VaR before — existing book as-is
    w_before = np.array([current_weights.get(t, 0) for t in tickers])
    var_quad_before = float(w_before @ cov @ w_before)
    vol_before_annual = np.sqrt(var_quad_before) if var_quad_before > 0 else 0.0
    var_before_daily = z * vol_before_annual / np.sqrt(252)

    # VaR after — strict addition; do NOT renormalize
    idx = tickers.index(new_ticker)
    w_after = w_before.copy()
    w_after[idx] += new_weight

    var_quad_after = float(w_after @ cov @ w_after)
    vol_after_annual = np.sqrt(var_quad_after) if var_quad_after > 0 else 0.0
    var_after_daily = z * vol_after_annual / np.sqrt(252)

    marginal = var_after_daily - var_before_daily

    # Standalone VaR contribution of the new position (no diversification)
    own_var_quad = (new_weight ** 2) * float(cov[idx, idx])
    own_var_daily = z * np.sqrt(own_var_quad) / np.sqrt(252) if own_var_quad > 0 else 0.0

    # Diversifying iff actual marginal < standalone (negative correlation
    # with book is reducing the impact)
    diversifying = bool(marginal < own_var_daily * 0.95) if own_var_daily > 0 else False

    return {
        "marginal_var_pct": _clean(round(float(marginal * 100), 3)),
        "var_before_pct": _clean(round(float(var_before_daily * 100), 3)),
        "var_after_pct": _clean(round(float(var_after_daily * 100), 3)),
        "standalone_var_pct": _clean(round(float(own_var_daily * 100), 3)),
        "diversifying": diversifying,
    }


def pre_trade_risk_check(
    ticker: str,
    proposed_action: str,
    proposed_size_pct: float,
    current_positions: dict[str, dict],
    returns_dict: dict[str, list[float]],
    max_position_size: float | None = None,
    max_sector_pct: float | None = None,
    marginal_var_block_pct: float | None = None,
    silent_squeeze_threshold: float | None = None,
) -> dict:
    """
    Master pre-trade gate. Called before every trade execution.

    Returns approved=False on any of:
      - position effectively dead-zeroed (<0.5%)
      - marginal VaR breach > marginal_var_block_pct (default 3%)
      - silent squeeze: adjusted_size < proposed * silent_squeeze_threshold
        (the caller would not get the position they asked for; refuse rather
        than accept a much smaller position by surprise)

    Each block reason is enumerated in `reasons` and surfaced in the 422.
    """
    # Resolve thresholds from quant.limits (single source of truth)
    if max_position_size is None:
        max_position_size = _limits.MAX_POSITION_SIZE
    if max_sector_pct is None:
        max_sector_pct = _limits.MAX_SECTOR_PCT
    if marginal_var_block_pct is None:
        marginal_var_block_pct = _limits.MARGINAL_VAR_BLOCK_PCT
    if silent_squeeze_threshold is None:
        silent_squeeze_threshold = _limits.SILENT_SQUEEZE_THRESHOLD

    reasons = []
    block_reasons: list[str] = []
    adjusted_size = proposed_size_pct
    risk_metrics: dict = {}

    # 1. Position size limit
    if proposed_size_pct > max_position_size:
        adjusted_size = max_position_size
        reasons.append(f"Size capped from {proposed_size_pct*100:.1f}% to {max_position_size*100:.1f}% (max position limit)")

    # 2. Sector concentration
    ticker_sector = current_positions.get(ticker, {}).get("sector", "Unknown")
    sector_total = sum(
        info.get("weight", 0) for t, info in current_positions.items()
        if info.get("sector") == ticker_sector and t != ticker
    )
    if sector_total + adjusted_size > max_sector_pct:
        max_allowed = max(0, max_sector_pct - sector_total)
        if max_allowed < adjusted_size:
            adjusted_size = max_allowed
            reasons.append(
                f"Sector {ticker_sector} at {sector_total*100:.1f}% — capped to {max_allowed*100:.1f}% "
                f"(limit {max_sector_pct*100:.0f}%)"
            )
            if max_allowed <= 0:
                block_reasons.append(f"Sector {ticker_sector} fully allocated; no room for new exposure")

    # 3. Correlation check
    if ticker in returns_dict and returns_dict:
        existing_rets = {t: r for t, r in returns_dict.items() if t != ticker and t in current_positions}
        if existing_rets:
            corr_result = correlation_adjusted_size(
                adjusted_size, returns_dict[ticker], existing_rets
            )
            if corr_result["penalty"] > 0.1:
                adjusted_size = corr_result["adjusted_size"]
                reasons.append(
                    f"Correlation penalty: avg corr {corr_result['avg_correlation']:.2f}, "
                    f"size reduced by {corr_result['penalty']*100:.0f}%"
                )
            risk_metrics["avg_correlation"] = corr_result["avg_correlation"]

    # 4. Marginal VaR — hard block above threshold
    if len(returns_dict) >= 2:
        cov = compute_ewma_covariance(returns_dict)
        weights = {t: info.get("weight", 0) for t, info in current_positions.items()}
        mvar = compute_marginal_var(weights, ticker, adjusted_size, cov)
        risk_metrics["marginal_var"] = mvar
        mvar_pct = mvar.get("marginal_var_pct")
        if mvar_pct is not None and abs(mvar_pct) > marginal_var_block_pct:
            block_reasons.append(
                f"Marginal VaR breach: {mvar_pct:.2f}% > {marginal_var_block_pct:.1f}% threshold "
                f"(this trade adds too much risk to the existing book)"
            )
        elif mvar_pct is not None and abs(mvar_pct) > 2.0:
            reasons.append(f"Elevated marginal VaR impact: {mvar_pct}%")

    # 5. Silent-squeeze guard — refuse if adjusted size is much smaller than asked
    if proposed_size_pct > 0 and adjusted_size < proposed_size_pct * silent_squeeze_threshold:
        block_reasons.append(
            f"Risk adjustments squeezed size from {proposed_size_pct*100:.2f}% to "
            f"{adjusted_size*100:.2f}% (>50% reduction). Refusing rather than fill at a "
            f"materially different size."
        )

    # 6. Final dead-zone guard
    if adjusted_size <= _limits.MIN_POSITION_SIZE:
        block_reasons.append(
            f"Position too small after risk adjustments (<{_limits.MIN_POSITION_SIZE*100:.2f}%)"
        )

    approved = len(block_reasons) == 0

    return {
        "approved": approved,
        "ticker": ticker,
        "action": proposed_action,
        "original_size_pct": round(proposed_size_pct * 100, 2),
        "adjusted_size_pct": round(adjusted_size * 100, 2),
        "reasons": reasons + block_reasons,
        "block_reasons": block_reasons,
        "risk_metrics": risk_metrics,
    }
