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


# ────────────────────────────────────────────────────────────────────
# Per-user override resolution
# ────────────────────────────────────────────────────────────────────
# Map of override-table field name -> (module-level constant, default,
# env var name, label, description, scale, validation range).
#
# scale: how to convert a user-friendly UI value into the stored decimal
#   "pct"   -> user enters 5 (meaning 5%), stored as 0.05
#   "raw"   -> user enters 5.0, stored as 5.0
#
# Order matches the natural grouping on the /risk-config page.

PARAMS_META: dict[str, dict] = {
    "max_position_pct":            {"const": "MAX_POSITION_SIZE",         "env": "RISK_MAX_POSITION_PCT",         "scale": "pct", "range": (0.001, 0.20), "group": "position_limits", "label": "Max position size",         "desc": "Hard cap per single position (risk gate + optimizer)."},
    "max_sector_pct":              {"const": "MAX_SECTOR_PCT",            "env": "RISK_MAX_SECTOR_PCT",            "scale": "pct", "range": (0.05, 1.0),   "group": "position_limits", "label": "Max sector concentration", "desc": "Maximum allocation to one sector."},
    "min_position_pct":            {"const": "MIN_POSITION_SIZE",         "env": "RISK_MIN_POSITION_PCT",          "scale": "pct", "range": (0.0001, 0.05), "group": "position_limits", "label": "Min position size",        "desc": "Below this, trade is rejected as noise."},
    "var_confidence":              {"const": "VAR_CONFIDENCE",            "env": "RISK_VAR_CONFIDENCE",            "scale": "raw", "range": (0.80, 0.999), "group": "var_breaker",     "label": "VaR confidence",           "desc": "Parametric + Cornish-Fisher + bootstrap CI."},
    "marginal_var_block_pct":      {"const": "MARGINAL_VAR_BLOCK_PCT",    "env": "RISK_MARGINAL_VAR_BLOCK_PCT",    "scale": "raw", "range": (0.5, 20.0),   "group": "var_breaker",     "label": "Marginal VaR block threshold", "desc": "Trade rejected if it adds more than this to portfolio VaR (%)."},
    "drawdown_caution_pct":        {"const": "DRAWDOWN_CAUTION_PCT",      "env": "RISK_DD_CAUTION_PCT",            "scale": "raw", "range": (1.0, 30.0),   "group": "var_breaker",     "label": "Drawdown caution",         "desc": "First-tier drawdown warning level (%)."},
    "drawdown_warn_pct":           {"const": "DRAWDOWN_WARN_PCT",         "env": "RISK_DD_WARN_PCT",               "scale": "raw", "range": (1.0, 40.0),   "group": "var_breaker",     "label": "Drawdown warn",            "desc": "Second-tier drawdown warning level (%)."},
    "drawdown_critical_pct":       {"const": "DRAWDOWN_CRITICAL_PCT",     "env": "RISK_DD_CRITICAL_PCT",           "scale": "raw", "range": (1.0, 50.0),   "group": "var_breaker",     "label": "Drawdown critical",        "desc": "Third-tier drawdown circuit break (%). Must be > warn > caution."},
    "silent_squeeze_threshold":    {"const": "SILENT_SQUEEZE_THRESHOLD",  "env": "RISK_SILENT_SQUEEZE_THRESHOLD",  "scale": "raw", "range": (0.1, 1.0),    "group": "var_breaker",     "label": "Silent-squeeze guard",     "desc": "Refuse fill if size shrinks below this fraction of requested."},
    "liquidity_max_pct_of_adv":    {"const": "LIQUIDITY_MAX_PCT_OF_ADV",  "env": "LIQ_MAX_PCT_OF_ADV",             "scale": "pct", "range": (0.005, 0.50), "group": "liquidity",       "label": "Liquidity max %ADV",       "desc": "Soft warning when position exceeds this fraction of avg daily volume."},
    "liquidity_block_pct_of_adv":  {"const": "LIQUIDITY_BLOCK_PCT_OF_ADV","env": "LIQ_BLOCK_PCT_OF_ADV",           "scale": "pct", "range": (0.01, 1.0),   "group": "liquidity",       "label": "Liquidity block %ADV",     "desc": "Hard block when position exceeds this fraction of avg daily volume."},
    "liquidity_participation_rate":{"const": "LIQUIDITY_PARTICIPATION_RATE","env": "LIQ_PARTICIPATION_RATE",       "scale": "pct", "range": (0.05, 1.0),   "group": "liquidity",       "label": "Participation rate",       "desc": "Used for days-to-liquidate estimate."},
    "liquidity_spread_warn_bps":   {"const": "LIQUIDITY_SPREAD_WARN_BPS", "env": "LIQ_SPREAD_WARN_BPS",            "scale": "raw", "range": (1.0, 500.0),  "group": "liquidity",       "label": "Spread warn (bps)",        "desc": "Bid-ask spread above this flags a name as wide / costly."},
    "optimizer_tx_cost_bps":       {"const": "OPTIMIZER_TX_COST_BPS",     "env": "OPT_TX_COST_BPS",                "scale": "raw", "range": (0.0, 100.0),  "group": "optimizer",       "label": "Optimizer turnover cost",  "desc": "Penalty deducted in mean-variance objective (bps)."},
    "optimizer_ridge_lambda":      {"const": "OPTIMIZER_RIDGE_LAMBDA",    "env": "OPT_RIDGE_LAMBDA",               "scale": "raw", "range": (0.0, 1.0),    "group": "optimizer",       "label": "Optimizer ridge λ",        "desc": "Tikhonov regularization on ill-conditioned covariance."},
    "vif_max_threshold":           {"const": "VIF_MAX_THRESHOLD",         "env": "FACTOR_VIF_MAX",                 "scale": "raw", "range": (1.0, 100.0),  "group": "optimizer",       "label": "VIF max threshold",        "desc": "Multicollinearity warning threshold for multi-factor regression."},
}


def _module_default(field: str) -> float | None:
    """Return the module-level constant value for a given field name."""
    meta = PARAMS_META.get(field)
    if meta is None:
        return None
    return globals().get(meta["const"])


def resolve_for_user(user_overrides: dict | None) -> dict:
    """
    Merge user overrides with the platform defaults. Returns a flat dict
    of {field: float} keyed by the override-table column names. NULL/missing
    values fall back to the live module-level constants (which already
    incorporate env-var overrides).

    Pass the result to trade-sizing functions via explicit kwargs.
    """
    overrides = user_overrides or {}
    out: dict[str, float] = {}
    for field in PARAMS_META:
        v = overrides.get(field)
        if v is None:
            v = _module_default(field)
        if v is not None:
            out[field] = float(v)
    return out


def merged_view(user_overrides: dict | None) -> list[dict]:
    """
    Build a UI-friendly merged view of every parameter, indicating whether
    each one is user-overridden, env-overridden, or hardcoded default.

    Returns a list of dicts in PARAMS_META order, with fields:
      field, label, desc, group, value, default, source, scale, range
    """
    overrides = user_overrides or {}
    rows = []
    for field, meta in PARAMS_META.items():
        user_v = overrides.get(field)
        module_v = _module_default(field)
        env_present = bool(os.environ.get(meta["env"]))

        if user_v is not None:
            source = "user"
            value = float(user_v)
        elif env_present:
            source = "env"
            value = float(module_v) if module_v is not None else 0.0
        else:
            source = "default"
            value = float(module_v) if module_v is not None else 0.0

        rows.append({
            "field": field,
            "label": meta["label"],
            "desc": meta["desc"],
            "group": meta["group"],
            "value": value,
            "default": float(module_v) if module_v is not None else None,
            "source": source,
            "scale": meta["scale"],
            "range_min": meta["range"][0],
            "range_max": meta["range"][1],
        })
    return rows


def validate_overrides(fields: dict) -> tuple[dict, list[str]]:
    """
    Validate a partial-update payload against the PARAMS_META ranges and
    cross-field invariants (drawdown caution < warn < critical, etc.).

    Returns (cleaned_dict, errors). cleaned_dict only contains valid
    entries; errors lists human-readable validation messages.
    """
    cleaned: dict = {}
    errors: list[str] = []

    for field, value in fields.items():
        if field not in PARAMS_META:
            errors.append(f"Unknown field: {field}")
            continue
        # Allow None — explicit reset to default
        if value is None:
            cleaned[field] = None
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            errors.append(f"{field}: must be numeric")
            continue
        meta = PARAMS_META[field]
        lo, hi = meta["range"]
        if v < lo or v > hi:
            errors.append(f"{field}: {v} outside allowed range [{lo}, {hi}]")
            continue
        cleaned[field] = v

    # Cross-field: drawdown caution < warn < critical (only when all three
    # are present in the cleaned payload; otherwise resolve in resolve_for_user).
    dd_keys = ("drawdown_caution_pct", "drawdown_warn_pct", "drawdown_critical_pct")
    if all(k in cleaned and cleaned[k] is not None for k in dd_keys):
        caution, warn, critical = (cleaned[k] for k in dd_keys)
        if not (caution < warn < critical):
            errors.append("Drawdown tiers must satisfy: caution < warn < critical")

    return cleaned, errors
