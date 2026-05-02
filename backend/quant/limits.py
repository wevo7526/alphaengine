"""
Single source of truth for risk and sizing thresholds.

Why this module exists: before, the same parameter was hardcoded in three
places — `risk.py`'s `pre_trade_risk_check(max_position_size=0.05)`,
`optimizer.py`'s `bounds = [(0, 0.20)]`, and `desk3_position_risk.py`'s
`evaluate_trade_gate(max_position_size=0.05)`. The optimizer's 20% silently
overrode the risk gate's 5% any time someone wired them differently. One
file, one constant, one truth.

Override at runtime via env vars (RISK_MAX_POSITION_PCT, etc.) so deploy
configs can tighten/loosen without code changes.
"""

from __future__ import annotations

import os


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if not raw:
        return default
    try:
        v = float(raw)
        return v
    except ValueError:
        return default


# ---- Position limits (decimal, not percent) ----
MAX_POSITION_SIZE: float = _env_float("RISK_MAX_POSITION_PCT", 0.05)   # 5% per name
MAX_SECTOR_PCT: float = _env_float("RISK_MAX_SECTOR_PCT", 0.30)         # 30% per sector
MIN_POSITION_SIZE: float = _env_float("RISK_MIN_POSITION_PCT", 0.005)   # below = noise

# ---- VaR / circuit breaker thresholds ----
VAR_CONFIDENCE: float = _env_float("RISK_VAR_CONFIDENCE", 0.95)
DRAWDOWN_CAUTION_PCT: float = _env_float("RISK_DD_CAUTION_PCT", 5.0)
DRAWDOWN_WARN_PCT: float = _env_float("RISK_DD_WARN_PCT", 7.0)
DRAWDOWN_CRITICAL_PCT: float = _env_float("RISK_DD_CRITICAL_PCT", 10.0)

# ---- Marginal VaR block threshold (% portfolio impact) ----
MARGINAL_VAR_BLOCK_PCT: float = _env_float("RISK_MARGINAL_VAR_BLOCK_PCT", 3.0)

# ---- Silent-squeeze guard: refuse if adjusted < proposed * threshold ----
SILENT_SQUEEZE_THRESHOLD: float = _env_float("RISK_SILENT_SQUEEZE_THRESHOLD", 0.5)

# ---- Liquidity gate ----
LIQUIDITY_MAX_PCT_OF_ADV: float = _env_float("LIQ_MAX_PCT_OF_ADV", 0.10)
LIQUIDITY_BLOCK_PCT_OF_ADV: float = _env_float("LIQ_BLOCK_PCT_OF_ADV", 0.25)
# Participation rate used for days-to-liquidate estimate. 25% is a desk-style
# upper bound — exceeding this routinely moves the market against you.
LIQUIDITY_PARTICIPATION_RATE: float = _env_float("LIQ_PARTICIPATION_RATE", 0.25)
# Bid-ask spread above this (in bps) flags a name as wide / costly to trade.
LIQUIDITY_SPREAD_WARN_BPS: float = _env_float("LIQ_SPREAD_WARN_BPS", 50.0)

# ---- Optimizer turnover penalty + ill-conditioning regularizer ----
OPTIMIZER_TX_COST_BPS: float = _env_float("OPT_TX_COST_BPS", 10.0)
# Tikhonov regularization applied to the covariance matrix when its condition
# number exceeds OPTIMIZER_RIDGE_TRIGGER_COND. λ is multiplied by mean-variance
# scale so it doesn't dominate the diagonal on well-conditioned matrices.
OPTIMIZER_RIDGE_LAMBDA: float = _env_float("OPT_RIDGE_LAMBDA", 0.01)
OPTIMIZER_RIDGE_TRIGGER_COND: float = _env_float("OPT_RIDGE_TRIGGER_COND", 1e10)

# ---- Multicollinearity guard for multi-factor regression ----
# Standard threshold: VIF > 10 indicates a factor is mostly explained by the
# other factors (multicollinearity). Surfaced as a flag, not a block.
VIF_MAX_THRESHOLD: float = _env_float("FACTOR_VIF_MAX", 10.0)


def z_for_confidence(confidence: float) -> float:
    """
    Inverse normal CDF for VaR z-score. Replaces a hardcoded
    `{0.95: 1.645, 0.99: 2.326}` lookup that silently fell back to 1.645
    on any other confidence value (so 0.999 looked the same as 0.95).

    Uses scipy.stats.norm.ppf for correctness across the full (0, 1) range.
    """
    from scipy.stats import norm
    return float(norm.ppf(confidence))


def as_dict() -> dict:
    """Snapshot of all live thresholds — surfaced via /api/system/info."""
    return {
        "max_position_pct": round(MAX_POSITION_SIZE * 100, 2),
        "max_sector_pct": round(MAX_SECTOR_PCT * 100, 2),
        "min_position_pct": round(MIN_POSITION_SIZE * 100, 3),
        "var_confidence": VAR_CONFIDENCE,
        "drawdown_caution_pct": DRAWDOWN_CAUTION_PCT,
        "drawdown_warn_pct": DRAWDOWN_WARN_PCT,
        "drawdown_critical_pct": DRAWDOWN_CRITICAL_PCT,
        "marginal_var_block_pct": MARGINAL_VAR_BLOCK_PCT,
        "silent_squeeze_threshold": SILENT_SQUEEZE_THRESHOLD,
        "liquidity_max_pct_of_adv": LIQUIDITY_MAX_PCT_OF_ADV,
        "liquidity_block_pct_of_adv": LIQUIDITY_BLOCK_PCT_OF_ADV,
        "liquidity_participation_rate": LIQUIDITY_PARTICIPATION_RATE,
        "liquidity_spread_warn_bps": LIQUIDITY_SPREAD_WARN_BPS,
        "optimizer_tx_cost_bps": OPTIMIZER_TX_COST_BPS,
        "optimizer_ridge_lambda": OPTIMIZER_RIDGE_LAMBDA,
        "vif_max_threshold": VIF_MAX_THRESHOLD,
    }
