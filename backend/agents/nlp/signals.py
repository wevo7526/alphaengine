"""
The NLP→signal contract (Build Plan §2.3).

Every NLP pass — filing-change scoring, earnings-call tone, 8-K novelty,
news sentiment — emits a typed `NLPSignal`, never prose. Signals feed the
conviction model **deterministically** (`aggregate_nlp_tilt`); the raw
passages they were derived from become Phase-1 source receipts. The LLM
extracts and classifies; it never decides the weights.

    NLPSignal {
      ticker, signal_name, value, direction, confidence,
      evidence_ids[], model, generated_at, detail
    }
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SignalName = Literal[
    "filing_change",      # YoY 10-K/10-Q language change (Lazy Prices)
    "call_tone",          # earnings-call management tone + delta vs prior call
    "news_sentiment",     # aggregate news sentiment
    "event_novelty",      # 8-K unusual vs recent cadence
    "revision_momentum",  # analyst estimate revisions (Phase 3 backlog)
]

Direction = Literal["bullish", "bearish", "neutral"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NLPSignal(BaseModel):
    """One typed analytical signal extracted from text."""

    model_config = ConfigDict(extra="ignore")

    ticker: str
    signal_name: SignalName
    # Magnitude in [0, 1]: how strong the signal is, sign-agnostic. The
    # `direction` carries the bullish/bearish interpretation. (Keeping value
    # unsigned makes the deterministic weighting in aggregate_nlp_tilt
    # transparent: tilt = Σ weight · dir · value · confidence.)
    value: float = 0.0
    direction: Direction = "neutral"
    confidence: float = 0.5  # [0, 1] — how much to trust this extraction
    evidence_ids: list[str] = Field(default_factory=list)  # content_hashes of source receipts
    model: str = "deterministic"  # e.g. "tfidf+haiku", "vader", "rule"
    generated_at: str = Field(default_factory=_now_iso)
    detail: dict = Field(default_factory=dict)  # signal-specific structured extras

    @field_validator("ticker", mode="before")
    @classmethod
    def _upper(cls, v):
        return (str(v or "").strip().upper())

    @field_validator("value", "confidence", mode="before")
    @classmethod
    def _clamp01(cls, v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.0


# Default sub-score weights for the conviction tilt. These are the seeds of
# the Phase 3.4 calibration loop — explicit and re-weightable, never an LLM
# mood score. filing_change is weighted highest because the documented
# (Lazy Prices) edge is the most robust of the four.
DEFAULT_WEIGHTS: dict[str, float] = {
    "filing_change": 0.35,
    "call_tone": 0.25,
    "event_novelty": 0.20,
    "news_sentiment": 0.15,
    "revision_momentum": 0.05,
}

_DIR_SIGN = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}


def aggregate_nlp_tilt(
    signals: list[NLPSignal],
    weights: dict[str, float] | None = None,
) -> dict:
    """Deterministically fold typed signals into a conviction tilt.

    Returns:
        {
          "tilt": float in [-1, 1],          # signed: + bullish, - bearish
          "contributions": [                  # per-signal, for the audit view
             {signal_name, ticker, direction, value, confidence,
              weight, contribution}
          ],
          "n_signals": int,
        }

    This is the deterministic consumption point the Build Plan requires
    (§2.3 / §2.5) and the thing `nlp_audit` ablates: zeroing the signals
    must move `tilt`.
    """
    w = weights or DEFAULT_WEIGHTS
    contributions = []
    weighted_sum = 0.0
    weight_total = 0.0
    for s in signals:
        sign = _DIR_SIGN.get(s.direction, 0.0)
        weight = float(w.get(s.signal_name, 0.0))
        contribution = weight * sign * s.value * s.confidence
        weighted_sum += contribution
        weight_total += weight * s.confidence  # normalizer uses applied weight
        contributions.append({
            "signal_name": s.signal_name,
            "ticker": s.ticker,
            "direction": s.direction,
            "value": round(s.value, 4),
            "confidence": round(s.confidence, 4),
            "weight": weight,
            "contribution": round(contribution, 6),
        })
    # Normalize by the applied weight mass so tilt stays in [-1, 1] regardless
    # of how many signals fired; falls back to raw sum if nothing weighted.
    tilt = (weighted_sum / weight_total) if weight_total > 0 else 0.0
    tilt = max(-1.0, min(1.0, tilt))
    return {
        "tilt": round(tilt, 6),
        "contributions": contributions,
        "n_signals": len(signals),
    }


def tilt_by_ticker(signals: list[NLPSignal], weights: dict[str, float] | None = None) -> dict[str, dict]:
    """Per-ticker conviction tilt — what the Strategist consumes per name."""
    by_tk: dict[str, list[NLPSignal]] = {}
    for s in signals:
        by_tk.setdefault(s.ticker, []).append(s)
    return {tk: aggregate_nlp_tilt(sigs, weights) for tk, sigs in by_tk.items()}
