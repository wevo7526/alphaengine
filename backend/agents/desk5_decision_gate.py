"""
Desk 5B — Decision Gate.

Pure programmatic logic. Makes the final GO / NO-GO / WATCH recommendation
based on hard thresholds:

- GO: top conviction >= 75 AND risk level not extreme AND regime-aligned
- WATCH: top conviction 50-74 OR risk level elevated+
- NO-GO: top conviction < 50 OR risk level extreme OR regime hostile

The Decision Gate is what separates a research tool from a fund. It commits
to a directional call based on measurable criteria, not LLM prose.
"""

import logging

logger = logging.getLogger(__name__)


# Regime compatibility with bullish/bearish stance
_REGIME_BIAS = {
    "expansion": {"bullish_ok": True, "bearish_ok": False, "note": "expansion favors risk-on"},
    "recovery": {"bullish_ok": True, "bearish_ok": False, "note": "recovery favors risk-on"},
    "late_cycle": {"bullish_ok": None, "bearish_ok": None, "note": "late-cycle is mixed"},
    "contraction": {"bullish_ok": False, "bearish_ok": True, "note": "contraction favors risk-off"},
    "unknown": {"bullish_ok": None, "bearish_ok": None, "note": "regime unclear"},
}


def compute_decision(
    trade_ideas: list[dict],
    macro_regime: str,
    overall_risk_level: str,
    min_conviction_go: int = 75,
    min_conviction_watch: int = 50,
    scorecard: dict | None = None,
) -> dict:
    """
    Evaluate whether to GO, WATCH, or NO-GO on the overall recommendation.

    Args:
        trade_ideas: list of trade idea dicts with direction + conviction
        macro_regime: expansion | late_cycle | contraction | recovery | unknown
        overall_risk_level: low | moderate | elevated | high | extreme
        scorecard: optional, the user's own track record summary (from
            scorer.get_scorecard_summary). When provided with >=10 scored
            signals, the gate computes a track-record multiplier:
              - 5d hit rate >= 60% with >=20 signals: +1.10x confidence
              - 5d hit rate <= 45% with >=20 signals: -0.85x confidence
              - by_conviction shows monotonic hit rate (high>med>low):
                +0.05x bonus (calibrated picker)
              - by_conviction shows inverted curve: -0.10x penalty
                (overconfidence — high-conviction is actually worse)
            Bucket data lets the gate punish a desk-style that historically
            underperforms instead of treating all conviction levels the same.

    Returns:
        {
          decision: "GO" | "WATCH" | "NO-GO",
          reason: str,
          confidence: int (0-100),
          top_conviction: int,
          regime_aligned: bool,
          track_record_adjustment: dict | None,
        }
    """
    if not trade_ideas:
        return {
            "decision": "NO-GO",
            "reason": "No trade ideas generated",
            "confidence": 0,
            "top_conviction": 0,
            "regime_aligned": False,
        }

    # Top conviction across all ideas
    convictions = [int(t.get("conviction", 0) or 0) for t in trade_ideas]
    top_conviction = max(convictions) if convictions else 0

    # Find the highest-conviction idea's direction
    top_idea = max(trade_ideas, key=lambda t: int(t.get("conviction", 0) or 0))
    top_direction = (top_idea.get("direction") or "").lower()
    is_bullish = "bullish" in top_direction
    is_bearish = "bearish" in top_direction

    # Check regime alignment
    regime_key = (macro_regime or "unknown").lower().replace(" ", "_")
    regime_info = _REGIME_BIAS.get(regime_key, _REGIME_BIAS["unknown"])
    regime_aligned = True
    regime_note = regime_info["note"]
    if is_bullish and regime_info["bullish_ok"] is False:
        regime_aligned = False
    elif is_bearish and regime_info["bearish_ok"] is False:
        regime_aligned = False

    # Risk level gates
    risk_lower = (overall_risk_level or "elevated").lower()
    risk_extreme = risk_lower in ("extreme",)
    risk_high = risk_lower in ("high", "extreme")

    # Decision logic
    reasons = []
    if top_conviction < min_conviction_watch:
        decision = "NO-GO"
        reasons.append(f"Top conviction {top_conviction} below WATCH threshold ({min_conviction_watch})")
    elif risk_extreme:
        decision = "NO-GO"
        reasons.append(f"Risk level {risk_lower.upper()} — too dangerous for new positions")
    elif top_conviction < min_conviction_go:
        decision = "WATCH"
        reasons.append(f"Conviction {top_conviction} in WATCH range ({min_conviction_watch}-{min_conviction_go - 1})")
        if not regime_aligned:
            reasons.append(f"Regime {regime_key.upper()} creates headwind — {regime_note}")
    elif not regime_aligned:
        decision = "WATCH"
        reasons.append(f"Conviction {top_conviction} strong but regime {regime_key.upper()} opposes — downgraded to WATCH")
        reasons.append(regime_note)
    elif risk_high:
        decision = "WATCH"
        reasons.append(f"Conviction {top_conviction} strong but risk {risk_lower.upper()} — proceed with caution")
    else:
        decision = "GO"
        reasons.append(f"Conviction {top_conviction} above GO threshold, risk {risk_lower}, regime aligned")

    # Confidence = top_conviction weighted by regime alignment + risk factor
    confidence = float(top_conviction)
    if not regime_aligned:
        confidence *= 0.8
    if risk_high:
        confidence *= 0.85

    # Track-record adjustment from the user's actual scorecard.
    track_record_adjustment: dict | None = None
    if scorecard and scorecard.get("signals", 0) >= 10:
        signals_n = int(scorecard.get("signals") or 0)
        hr_5d = scorecard.get("hit_rate_5d")
        by_conv = scorecard.get("by_conviction") or {}
        multiplier = 1.0
        notes: list[str] = []

        if signals_n >= 20 and hr_5d is not None:
            if hr_5d >= 60:
                multiplier *= 1.10
                notes.append(f"5d hit rate {hr_5d}% (n={signals_n}) — strong track record, +10%")
            elif hr_5d <= 45:
                multiplier *= 0.85
                notes.append(f"5d hit rate {hr_5d}% (n={signals_n}) — weak track record, -15%")

        # Calibration check: is high-conviction actually winning more?
        bucket_hits = []
        for bucket_label in ["low", "medium", "high", "very_high"]:
            stats = by_conv.get(bucket_label)
            if isinstance(stats, dict) and stats.get("count", 0) >= 5 and stats.get("hit_rate_5d") is not None:
                bucket_hits.append((bucket_label, stats["hit_rate_5d"], stats["count"]))
        if len(bucket_hits) >= 2:
            rates = [b[1] for b in bucket_hits]
            monotonic_up = all(rates[i] <= rates[i + 1] for i in range(len(rates) - 1))
            monotonic_down = all(rates[i] >= rates[i + 1] for i in range(len(rates) - 1))
            spread = max(rates) - min(rates)
            if monotonic_up and spread >= 5:
                multiplier *= 1.05
                notes.append("Conviction is well-calibrated (monotonic hit rate), +5%")
            elif monotonic_down and spread >= 5:
                multiplier *= 0.90
                notes.append("Conviction is INVERSELY calibrated (high-conviction worst), -10%")

        if multiplier != 1.0:
            confidence *= multiplier
            track_record_adjustment = {
                "multiplier": round(multiplier, 3),
                "signals_evaluated": signals_n,
                "hit_rate_5d": hr_5d,
                "notes": notes,
            }
            reasons.append(f"Track record multiplier: ×{multiplier:.2f}")

    confidence = int(max(0, min(100, confidence)))

    return {
        "decision": decision,
        "reason": " · ".join(reasons),
        "confidence": confidence,
        "top_conviction": top_conviction,
        "regime_aligned": regime_aligned,
        "regime": regime_key,
        "risk_level": risk_lower,
        "track_record_adjustment": track_record_adjustment,
    }
