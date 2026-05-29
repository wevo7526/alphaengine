"""
8-K novelty (Build Plan §2.1d).

Flags 8-Ks whose content is unusual vs. the company's recent cadence. Works
off the *listing* metadata (item codes + dates) — no section extraction — so
it costs at most one cheap sec-api listing call (budget-guarded), or zero when
the caller already has the filings list.

Deterministic scorer + signal builder are pure/testable; the fetch is gated
and injectable.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 8-K item codes that carry a directional read. Most items are neutral
# (routine disclosure); these few are reliably informative.
_ITEM_DIRECTION = {
    "4.02": "bearish",  # Non-reliance on previously issued financials (restatement)
    "2.06": "bearish",  # Material impairments
    "2.04": "bearish",  # Triggering events accelerating a debt obligation
    "5.02": "neutral",  # Departure/appointment of directors/officers (ambiguous)
    "2.02": "neutral",  # Results of operations (earnings) — magnitude unknown here
    "1.01": "neutral",  # Entry into a material agreement
    "8.01": "neutral",  # Other events
}


def _items_of(f: dict) -> list[str]:
    """Extract 8-K item codes from a sec-api filing record."""
    items = f.get("items") or f.get("itemCodes") or []
    if isinstance(items, str):
        items = [items]
    out = []
    for it in items:
        s = str(it)
        # Normalize "Item 2.02: Results..." → "2.02"
        import re
        m = re.search(r"\d+\.\d+", s)
        if m:
            out.append(m.group(0))
    return out


def score_8k_novelty(filings: list[dict]) -> dict:
    """Score how novel the most-recent 8-K is vs. the trailing window.

    `filings`: sec-api 8-K records, newest first, each with `items`/`filedAt`.
    Returns {novelty, novel_items[], latest_items[], direction, n_history}.
    novelty ∈ [0,1] = fraction of the latest filing's item codes not seen in
    the prior filings.
    """
    if not filings:
        return {"novelty": 0.0, "novel_items": [], "latest_items": [],
                "direction": "neutral", "n_history": 0}
    latest_items = _items_of(filings[0])
    history_items: set[str] = set()
    for f in filings[1:]:
        history_items.update(_items_of(f))
    if not latest_items:
        return {"novelty": 0.0, "novel_items": [], "latest_items": [],
                "direction": "neutral", "n_history": len(filings) - 1}
    novel = [it for it in latest_items if it not in history_items]
    novelty = len(novel) / len(latest_items)
    # Direction: worst (bearish-leaning) directional item among the latest set.
    direction = "neutral"
    for it in latest_items:
        if _ITEM_DIRECTION.get(it) == "bearish":
            direction = "bearish"
            break
    return {
        "novelty": round(novelty, 4),
        "novel_items": novel,
        "latest_items": latest_items,
        "direction": direction,
        "n_history": len(filings) - 1,
    }


def build_event_novelty_signal(ticker: str, score: dict, *, accession: str | None = None, url: str | None = None):
    """Build an `event_novelty` NLPSignal (+ a single descriptive receipt)."""
    from agents.nlp.signals import NLPSignal
    from provenance import source_receipt

    novelty = float(score.get("novelty", 0.0))
    if novelty <= 0 and score.get("direction") == "neutral":
        return None, []
    items = ", ".join(score.get("latest_items") or [])
    novel = ", ".join(score.get("novel_items") or [])
    passage = f"Latest 8-K items: [{items}]. Novel vs recent cadence: [{novel}]."
    receipt = source_receipt(
        "sec", f"8k-novelty:{accession or ticker}", passage, ticker=ticker, url=url,
        label=f"8-K novelty · {ticker}",
    )
    sig = NLPSignal(
        ticker=ticker, signal_name="event_novelty", value=novelty,
        direction=score.get("direction", "neutral"),
        confidence=round(min(0.7, 0.3 + 0.4 * novelty), 4),
        evidence_ids=[receipt["content_hash"]], model="rule",
        detail={"novel_items": score.get("novel_items"), "latest_items": score.get("latest_items")},
    )
    return sig, [receipt]
