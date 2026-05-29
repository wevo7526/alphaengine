"""
Conviction as a decomposable, receipted composite + calibration loop
(Build Plan §3.4).

Conviction is NOT an LLM mood score. It's a deterministic weighted blend of
named sub-scores — factor, revision_momentum, filing_change, call_tone,
options_positioning, regime_fit — each in signed [-1, 1] (positive = bullish)
with an explicit weight. Every sub-score is a receipt, so a PM can see exactly
why an idea is a 72 and not an 85.

The calibration loop logs conviction vs. realized outcome and reports a
reliability curve + Brier score, then suggests re-weighting sub-scores by
their realized predictive value — closing the loop that compounds into a moat.
"""

from __future__ import annotations

import math

# Explicit, re-weightable sub-score weights (must be > 0; normalized at use).
DEFAULT_SUBSCORE_WEIGHTS: dict[str, float] = {
    "factor": 0.25,
    "filing_change": 0.20,
    "call_tone": 0.15,
    "revision_momentum": 0.15,
    "options_positioning": 0.15,
    "regime_fit": 0.10,
}


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compose_conviction(subscores: dict, weights: dict | None = None) -> dict:
    """Blend signed sub-scores into a conviction magnitude + direction.

    `subscores`: {name: value} or {name: {"value": v, "confidence": c}} where
    value ∈ [-1, 1] (positive = bullish). Missing sub-scores are skipped and
    the remaining weights renormalized. Returns:
        {conviction (0-100), direction, net (signed [-1,1]),
         contributions: [{name, value, confidence, weight, contribution}],
         receipts: [computed_receipt]}
    """
    from provenance import computed_receipt

    w = weights or DEFAULT_SUBSCORE_WEIGHTS
    contributions = []
    net = 0.0
    weight_mass = 0.0
    for name, raw in (subscores or {}).items():
        if name not in w:
            continue
        if isinstance(raw, dict):
            value = float(raw.get("value", 0.0) or 0.0)
            conf = float(raw.get("confidence", 1.0) or 0.0)
        else:
            value = float(raw or 0.0)
            conf = 1.0
        value = _clamp(value, -1.0, 1.0)
        conf = _clamp(conf, 0.0, 1.0)
        weight = float(w[name])
        contrib = weight * value * conf
        net += contrib
        weight_mass += weight * conf
        contributions.append({
            "name": name, "value": round(value, 4), "confidence": round(conf, 4),
            "weight": weight, "contribution": round(contrib, 6),
        })

    net = (net / weight_mass) if weight_mass > 0 else 0.0
    net = _clamp(net, -1.0, 1.0)
    direction = "bullish" if net > 0.02 else "bearish" if net < -0.02 else "neutral"
    # Magnitude: 50 baseline + agreement strength. Strong, aligned sub-scores
    # → high conviction; weak/conflicting → near 50.
    conviction = round(_clamp(50.0 + 50.0 * abs(net), 0.0, 100.0))

    receipts = [
        computed_receipt(
            f"conviction sub-score: {c['name']}", c["contribution"],
            formula_ref="quant.conviction.compose_conviction",
            inputs={"value": c["value"], "confidence": c["confidence"], "weight": c["weight"]},
            source_name="engine",
            label=f"{c['name']} → {c['contribution']:+.4f}",
        )
        for c in contributions
    ]
    receipts.append(computed_receipt(
        "conviction (composite)", conviction,
        formula_ref="quant.conviction.compose_conviction",
        inputs={"net": round(net, 4), "n_subscores": len(contributions)},
        source_name="engine", label=f"conviction = {conviction} ({direction})",
    ))

    return {
        "conviction": conviction,
        "direction": direction,
        "net": round(net, 4),
        "contributions": contributions,
        "receipts": receipts,
    }


# ── Calibration: reliability curve + Brier score ────────────────────────

def brier_score(probs: list[float], outcomes: list[int]) -> float | None:
    """Mean squared error of probabilistic predictions. Lower is better.

    probs ∈ [0,1] (e.g. conviction/100 = P(direction correct)); outcomes ∈ {0,1}.
    """
    pairs = [(float(p), int(o)) for p, o in zip(probs, outcomes)
             if p is not None and o is not None]
    if not pairs:
        return None
    return round(sum((p - o) ** 2 for p, o in pairs) / len(pairs), 4)


def reliability_curve(probs: list[float], outcomes: list[int], n_bins: int = 10) -> list[dict]:
    """Bin predictions and report predicted vs. observed frequency per bin.

    A well-calibrated model has observed_freq ≈ mean_predicted in every bin.
    Returns [{bin_lo, bin_hi, n, mean_predicted, observed_freq}].
    """
    pairs = [(float(p), int(o)) for p, o in zip(probs, outcomes)
             if p is not None and o is not None]
    bins = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        sel = [(p, o) for p, o in pairs if (lo <= p < hi or (b == n_bins - 1 and p == hi))]
        if not sel:
            bins.append({"bin_lo": round(lo, 2), "bin_hi": round(hi, 2), "n": 0,
                         "mean_predicted": None, "observed_freq": None})
            continue
        bins.append({
            "bin_lo": round(lo, 2), "bin_hi": round(hi, 2), "n": len(sel),
            "mean_predicted": round(sum(p for p, _ in sel) / len(sel), 4),
            "observed_freq": round(sum(o for _, o in sel) / len(sel), 4),
        })
    return bins


def calibration_report(scored_rows: list[dict], horizon: str = "5d") -> dict:
    """Calibration over scored signals. Each row needs `conviction` and
    `hit_{horizon}` (bool/int). Returns Brier + reliability curve + counts.
    """
    hit_key = f"hit_{horizon}"
    probs, outcomes = [], []
    for r in scored_rows or []:
        conv = r.get("conviction")
        hit = r.get(hit_key)
        if conv is None or hit is None:
            continue
        probs.append(_clamp(float(conv) / 100.0, 0.0, 1.0))
        outcomes.append(1 if hit else 0)
    n = len(probs)
    return {
        "horizon": horizon,
        "n": n,
        "brier_score": brier_score(probs, outcomes),
        "base_rate": round(sum(outcomes) / n, 4) if n else None,
        "mean_conviction": round(sum(probs) / n, 4) if n else None,
        "reliability_curve": reliability_curve(probs, outcomes),
    }


def suggest_reweight(subscore_hit_rates: dict, *, floor: float = 0.02) -> dict:
    """Re-weight sub-scores by realized edge (hit_rate − 0.5), normalized.

    A sub-score with no realized edge collapses toward `floor`; one that
    predicts well gets more weight. Returns a normalized weight dict.
    """
    edges = {k: max(0.0, float(v) - 0.5) for k, v in (subscore_hit_rates or {}).items()}
    raw = {k: max(floor, e) for k, e in edges.items()}
    total = sum(raw.values())
    if total <= 0:
        return dict(DEFAULT_SUBSCORE_WEIGHTS)
    return {k: round(v / total, 4) for k, v in raw.items()}
