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

# ---- Optimizer turnover penalty ----
OPTIMIZER_TX_COST_BPS: float = _env_float("OPT_TX_COST_BPS", 10.0)


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
        "optimizer_tx_cost_bps": OPTIMIZER_TX_COST_BPS,
    }
