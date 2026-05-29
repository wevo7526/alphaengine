"""
NLP signal runner + deterministic conviction tilt (Build Plan §2.3 / §2.5).

Gathers the typed NLP signals (filing_change, call_tone, event_novelty) for
the names that reached the memo stage, then folds them into trade-idea
conviction **deterministically** — the LLM never sees the weights. This is the
consumption point the DoD requires and the thing `nlp_audit` ablates.

Everything is gated by the per-signal feature flags (all default OFF), so when
the user hasn't enabled filing/transcript NLP this is a no-op that returns an
empty bundle and leaves conviction untouched.
"""

from __future__ import annotations

import asyncio
import logging

from config import settings

logger = logging.getLogger(__name__)

# How many conviction points a full +1.0 tilt moves an idea. Deterministic,
# bounded so NLP nudges conviction rather than dominating it.
CONVICTION_TILT_SCALE = 15.0


async def gather_nlp_signals(tickers: list[str], *, max_names: int | None = None) -> dict:
    """Run the enabled NLP passes for up to `max_names` tickers.

    Returns {signals: [NLPSignal], receipts: [dict], cache_receipts: [dict],
             by_ticker_tilt: {ticker: tilt_obj}, coverage: {...}}.
    Never raises — a failing pass contributes nothing.
    """
    from agents.nlp.signals import NLPSignal, tilt_by_ticker

    filing_on = settings.FILING_NLP_ENABLED
    transcript_on = settings.TRANSCRIPT_NLP_ENABLED
    cap = max_names or settings.FILING_NLP_MAX_NAMES
    names = [t for t in dict.fromkeys((t or "").upper() for t in tickers) if t][:cap]

    bundle = {"signals": [], "receipts": [], "cache_receipts": [],
              "by_ticker_tilt": {}, "coverage": {}}
    if not names or not (filing_on or transcript_on):
        bundle["coverage"] = {"requested": len(tickers), "covered": 0,
                              "covered_pct": 0.0, "names": []}
        return bundle

    signals: list[NLPSignal] = []
    receipts: list[dict] = []
    cache_receipts: list[dict] = []
    covered: set[str] = set()

    for tk in names:
        try:
            if filing_on:
                from agents.nlp.filing_ingest import run_filing_change
                r = await run_filing_change(tk, section="1A")
                if r.get("signal"):
                    signals.append(r["signal"])
                    receipts.extend(r.get("receipts") or [])
                    covered.add(tk)
                cache_receipts.extend(r.get("cache_receipts") or [])
            if transcript_on:
                from agents.nlp.transcripts import run_call_tone
                r = await run_call_tone(tk)
                if r.get("signal"):
                    signals.append(r["signal"])
                    receipts.extend(r.get("receipts") or [])
                    covered.add(tk)
        except Exception as e:  # noqa: BLE001
            logger.warning("[nlp.runner] signal gather failed for %s: %s", tk, e)

    bundle["signals"] = signals
    bundle["receipts"] = receipts
    bundle["cache_receipts"] = cache_receipts
    bundle["by_ticker_tilt"] = tilt_by_ticker(signals)
    bundle["coverage"] = {
        "requested": len(tickers),
        "covered": len(covered),
        "covered_pct": round(100.0 * len(covered) / max(1, len(names)), 1),
        "names": sorted(covered),
    }
    logger.info("[nlp.runner] %d signals across %d/%d names",
                len(signals), len(covered), len(names))
    return bundle


def apply_nlp_tilt_to_ideas(
    trade_ideas: list[dict],
    by_ticker_tilt: dict,
    *,
    scale: float = CONVICTION_TILT_SCALE,
) -> tuple[list[dict], list[dict]]:
    """Deterministically nudge each idea's conviction by its ticker's NLP tilt.

    Returns (updated_ideas, adjustments). Each idea gets an `nlp_adjustment`
    block recording the original/adjusted conviction and the tilt — this is
    the receipt for the conviction sub-score (Phase 3.4 will formalize the
    whole composite). Pure function; the ablation harness calls it with real
    vs. zeroed tilts and asserts the rankings change.
    """
    adjustments = []
    for idea in trade_ideas:
        if not isinstance(idea, dict):
            continue
        tk = (idea.get("ticker") or "").upper()
        tilt_obj = by_ticker_tilt.get(tk)
        if not tilt_obj:
            continue
        tilt = float(tilt_obj.get("tilt", 0.0))
        if tilt == 0.0:
            continue
        try:
            orig = float(idea.get("conviction") or 0)
        except (TypeError, ValueError):
            orig = 0.0
        delta = tilt * scale
        adjusted = max(0.0, min(100.0, orig + delta))
        idea["conviction"] = round(adjusted)
        idea["nlp_adjustment"] = {
            "original_conviction": round(orig),
            "adjusted_conviction": round(adjusted),
            "tilt": round(tilt, 4),
            "delta": round(delta, 2),
            "contributions": tilt_obj.get("contributions", []),
        }
        adjustments.append({"ticker": tk, "from": round(orig),
                            "to": round(adjusted), "tilt": round(tilt, 4)})
    return trade_ideas, adjustments
