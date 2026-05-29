"""
Regime-conditional factor tilting (Build Plan §3.5).

Value, momentum, quality, low-volatility and size pay off differently across
the macro regime. Rather than running factor weights static, we tilt them by
the HMM regime *posterior* (quant.regime.classify_regime) — cheap, defensible,
and it reuses machinery we already have.

Also exposes `regime_fit_score`: how well a given idea's style fits the
current regime, in signed [-1, 1] — the `regime_fit` sub-score consumed by
quant.conviction.compose_conviction (§3.4).
"""

from __future__ import annotations

FACTORS = ("value", "momentum", "quality", "low_vol", "size")

# Per-regime factor preference profiles (relative, normalized at blend time).
# Grounded in the standard regime/factor literature:
#   risk_on    → cyclical value + momentum + small-cap size lead
#   late_cycle → quality + momentum hold up as breadth narrows
#   transition → defensives (low_vol, quality) take over
#   risk_off   → low_vol + quality dominate; value/size/momentum lag
_REGIME_FACTOR_PROFILES: dict[str, dict[str, float]] = {
    "risk_on":    {"value": 0.30, "momentum": 0.28, "quality": 0.12, "low_vol": 0.08, "size": 0.22},
    "late_cycle": {"value": 0.20, "momentum": 0.28, "quality": 0.30, "low_vol": 0.15, "size": 0.07},
    "transition": {"value": 0.15, "momentum": 0.15, "quality": 0.30, "low_vol": 0.35, "size": 0.05},
    "risk_off":   {"value": 0.10, "momentum": 0.08, "quality": 0.32, "low_vol": 0.45, "size": 0.05},
}

# Map common idea/style labels to a factor for regime-fit scoring.
_STYLE_TO_FACTOR = {
    "value": "value", "deep_value": "value", "gartman": "value",
    "momentum": "momentum", "trend": "momentum", "breakout": "momentum",
    "quality": "quality", "compounder": "quality", "wide_moat": "quality",
    "low_vol": "low_vol", "defensive": "low_vol", "min_vol": "low_vol",
    "small_cap": "size", "smid": "size", "micro_cap": "size",
}


def _normalize_probs(regime_probs: dict) -> dict[str, float]:
    probs = {k: max(0.0, float(regime_probs.get(k, 0.0) or 0.0)) for k in _REGIME_FACTOR_PROFILES}
    total = sum(probs.values())
    if total <= 0:
        # Unknown regime → uniform over the four states.
        return {k: 0.25 for k in _REGIME_FACTOR_PROFILES}
    return {k: v / total for k, v in probs.items()}


def regime_factor_tilts(regime_probs: dict) -> dict:
    """Blend per-regime factor profiles by the regime posterior.

    Returns {weights: {factor: w (sums to 1)}, dominant_regime, receipts}.
    """
    from provenance import computed_receipt

    probs = _normalize_probs(regime_probs)
    weights = {f: 0.0 for f in FACTORS}
    for regime, p in probs.items():
        profile = _REGIME_FACTOR_PROFILES[regime]
        for f in FACTORS:
            weights[f] += p * profile[f]
    total = sum(weights.values()) or 1.0
    weights = {f: round(w / total, 4) for f, w in weights.items()}
    dominant = max(probs, key=probs.get)

    receipts = [
        computed_receipt(
            f"factor tilt: {f}", weights[f],
            formula_ref="quant.regime_factors.regime_factor_tilts",
            inputs={"regime_probs": {k: round(v, 3) for k, v in probs.items()}},
            source_name="engine", label=f"{f} tilt = {weights[f]} ({dominant})",
        )
        for f in FACTORS
    ]
    return {"weights": weights, "dominant_regime": dominant,
            "regime_probs": {k: round(v, 4) for k, v in probs.items()}, "receipts": receipts}


def regime_fit_score(style_labels: list[str], regime_probs: dict) -> float:
    """How well an idea's style fits the current regime, signed [-1, 1].

    Compares the idea's factor exposure to the regime-tilted factor weights:
    a momentum idea in risk_on scores positive; the same idea in risk_off
    scores negative. Feeds conviction's `regime_fit` sub-score.
    """
    tilts = regime_factor_tilts(regime_probs)["weights"]
    # Factors the idea expresses.
    idea_factors = set()
    for lbl in (style_labels or []):
        f = _STYLE_TO_FACTOR.get(str(lbl).strip().lower())
        if f:
            idea_factors.add(f)
    if not idea_factors:
        return 0.0
    # Average tilt of the idea's factors, recentred so the equal-weight
    # baseline (0.20 each across 5 factors) maps to 0, and scaled to [-1, 1].
    avg_tilt = sum(tilts[f] for f in idea_factors) / len(idea_factors)
    baseline = 1.0 / len(FACTORS)  # 0.20
    # Max deviation from baseline is bounded by ~ (max_profile_weight - baseline).
    score = (avg_tilt - baseline) / baseline  # ~[-1, +1.x]
    return round(max(-1.0, min(1.0, score)), 4)
