"""
Filing-change scoring (Build Plan §2.1c) — the "Lazy Prices" signal.

Year-over-year *changes* in 10-K/10-Q language (esp. Risk Factors and MD&A)
predict negative forward returns; the market underreacts. We compute a
deterministic `filing_change_score` from the two section texts (cheap, no
API, no LLM) and optionally pass the changed passages to a cheap LLM
(Haiku tier) to *categorize* the material changes.

The deterministic core is pure and fully testable on fixtures — it never
touches sec-api. The LLM categorization is optional, injectable, and gated.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9']+")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
# Boilerplate lines that add noise to the diff (page markers, etc.).
_BOILERPLATE = re.compile(r"table of contents|^\s*\d+\s*$|form 10-[kq]", re.IGNORECASE)


def _normalize(text: str) -> str:
    return " ".join((text or "").split()).lower()


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(_normalize(text))


def cosine_tf(a: str, b: str) -> float:
    """Cosine similarity of word term-frequency vectors. Deterministic, [0,1].

    TF (bag-of-words) rather than TF-IDF: for a 2-document comparison IDF is
    degenerate, and raw TF cosine is the standard, transparent choice for
    measuring how much a single document's wording changed.
    """
    ca, cb = Counter(_tokens(a)), Counter(_tokens(b))
    if not ca or not cb:
        return 0.0
    common = set(ca) & set(cb)
    dot = sum(ca[t] * cb[t] for t in common)
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _ngrams(tokens: list[str], n: int) -> set[tuple]:
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def jaccard_ngrams(a: str, b: str, n: int = 3) -> float:
    """Jaccard similarity over word n-grams. Deterministic, [0,1]."""
    ga, gb = _ngrams(_tokens(a), n), _ngrams(_tokens(b), n)
    if not ga and not gb:
        return 1.0
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    union = len(ga | gb)
    return inter / union if union else 0.0


def _sentences(text: str) -> list[str]:
    out = []
    for s in _SENT_SPLIT.split(text or ""):
        s = s.strip()
        if len(s) < 25 or _BOILERPLATE.search(s):
            continue
        out.append(s)
    return out


def _sentence_diff(current: str, prior: str, cap: int = 6) -> tuple[list[str], list[str]]:
    """Added (in current, not prior) and removed (in prior, not current) sentences.

    Matched on a normalized fingerprint so trivial whitespace/case changes
    don't register as edits. Returns the longest `cap` of each (longest =
    most substantive change).
    """
    cur = _sentences(current)
    pri = _sentences(prior)
    pri_fp = {_normalize(s) for s in pri}
    cur_fp = {_normalize(s) for s in cur}
    added = [s for s in cur if _normalize(s) not in pri_fp]
    removed = [s for s in pri if _normalize(s) not in cur_fp]
    added.sort(key=len, reverse=True)
    removed.sort(key=len, reverse=True)
    return added[:cap], removed[:cap]


def _bucket(change_score: float) -> str:
    if change_score >= 0.55:
        return "severe"
    if change_score >= 0.35:
        return "high"
    if change_score >= 0.18:
        return "moderate"
    return "low"


def filing_change_score(current: str, prior: str, *, section: str = "1A") -> dict:
    """Deterministic YoY filing-change score. No API, no LLM.

    Returns:
        {
          section, cosine_similarity, jaccard_similarity, similarity,
          change_score (1 - similarity), magnitude_bucket,
          added_excerpts[], removed_excerpts[],
          n_added, n_removed, has_prior
        }
    """
    if not (current or "").strip():
        return {
            "section": section, "cosine_similarity": 0.0, "jaccard_similarity": 0.0,
            "similarity": 0.0, "change_score": 0.0, "magnitude_bucket": "low",
            "added_excerpts": [], "removed_excerpts": [], "n_added": 0,
            "n_removed": 0, "has_prior": bool((prior or "").strip()), "note": "no current text",
        }
    if not (prior or "").strip():
        # First filing we've seen — no YoY baseline. Not a change signal.
        return {
            "section": section, "cosine_similarity": 1.0, "jaccard_similarity": 1.0,
            "similarity": 1.0, "change_score": 0.0, "magnitude_bucket": "low",
            "added_excerpts": [], "removed_excerpts": [], "n_added": 0,
            "n_removed": 0, "has_prior": False, "note": "no prior filing",
        }

    cos = cosine_tf(current, prior)
    jac = jaccard_ngrams(current, prior, n=3)
    similarity = 0.5 * cos + 0.5 * jac
    change_score = max(0.0, min(1.0, 1.0 - similarity))
    added, removed = _sentence_diff(current, prior)
    return {
        "section": section,
        "cosine_similarity": round(cos, 4),
        "jaccard_similarity": round(jac, 4),
        "similarity": round(similarity, 4),
        "change_score": round(change_score, 4),
        "magnitude_bucket": _bucket(change_score),
        "added_excerpts": added,
        "removed_excerpts": removed,
        "n_added": len(added),
        "n_removed": len(removed),
        "has_prior": True,
    }


# ── Optional LLM categorization (Haiku tier; injectable; gated) ──────────

_CATEGORIZE_SYSTEM = (
    "You are a forensic 10-K/10-Q analyst. You are given the sentences ADDED to "
    "and REMOVED from a company's filing section versus the prior comparable "
    "filing. Classify the material changes. Respond as STRICT JSON only:\n"
    '{"summary": "<=2 sentences", "categories": ["new_risk_factor"|"removed_risk_factor"'
    '|"sentiment_shift"|"hedging_language"|"litigation"|"going_concern"|"guidance_change"|"boilerplate"], '
    '"direction": "bullish"|"bearish"|"neutral", "notable_changes": ["<short phrase>", ...]}\n'
    "Large, substantive additions of risk/hedging language are typically BEARISH "
    "(the Lazy Prices effect). Pure boilerplate reordering is neutral."
)


def categorize_changes_llm(
    score_obj: dict,
    ticker: str,
    *,
    llm=None,
) -> dict | None:
    """Categorize the changed passages with the cheap extraction-tier model.

    `llm` is injectable for tests. Returns None on any failure or when there's
    nothing material to categorize. Never raises.
    """
    added = score_obj.get("added_excerpts") or []
    removed = score_obj.get("removed_excerpts") or []
    if not added and not removed:
        return None
    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        from llm.client import get_llm, cache_system_block

        model = llm if llm is not None else get_llm("extraction")
        added_block = "\n".join(f"+ {s}" for s in added[:6])
        removed_block = "\n".join(f"- {s}" for s in removed[:6])
        human = (
            f"Ticker: {ticker}. Section: {score_obj.get('section')}. "
            f"Deterministic change_score={score_obj.get('change_score')} "
            f"({score_obj.get('magnitude_bucket')}).\n\n"
            f"ADDED:\n{added_block or '(none)'}\n\nREMOVED:\n{removed_block or '(none)'}"
        )
        resp = model.invoke([
            SystemMessage(content=cache_system_block(_CATEGORIZE_SYSTEM)),
            HumanMessage(content=human),
        ])
        import json
        text = (getattr(resp, "content", "") or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        start, end = text.find("{"), text.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        data = json.loads(text[start:end])
        return data if isinstance(data, dict) else None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[filing_diff] LLM categorization failed for {ticker}: {e}")
        return None


def build_filing_signal(
    ticker: str,
    score_obj: dict,
    *,
    llm_categorization: dict | None = None,
    accession: str | None = None,
    filing_url: str | None = None,
):
    """Turn a filing-change score into a typed NLPSignal + source receipts.

    Returns `(NLPSignal, list[receipt_dict])`. The changed passages become
    Phase-1 source receipts (citable evidence); the signal's `evidence_ids`
    are those receipts' content hashes. Returns `(None, [])` when there's no
    prior baseline (no YoY change to score).
    """
    from agents.nlp.signals import NLPSignal
    from provenance import source_receipt

    if not score_obj.get("has_prior"):
        return None, []

    section = score_obj.get("section", "1A")
    change = float(score_obj.get("change_score") or 0.0)
    bucket = score_obj.get("magnitude_bucket", "low")
    src_ref = f"{accession or 'unknown'}:{section}"

    # Source receipts for the most substantive changed passages.
    receipts: list[dict] = []
    for s in (score_obj.get("added_excerpts") or [])[:5]:
        receipts.append(source_receipt(
            "sec", src_ref, s, ticker=ticker, url=filing_url,
            label=f"10-K/Q §{section} ADDED · {ticker}",
        ))
    for s in (score_obj.get("removed_excerpts") or [])[:5]:
        receipts.append(source_receipt(
            "sec", src_ref, s, ticker=ticker, url=filing_url,
            label=f"10-K/Q §{section} REMOVED · {ticker}",
        ))
    evidence_ids = [r["content_hash"] for r in receipts]

    # Direction: Lazy Prices — a large, substantive change is BEARISH by
    # default. The LLM categorization overrides when it has a clear read.
    if llm_categorization and llm_categorization.get("direction") in ("bullish", "bearish", "neutral"):
        direction = llm_categorization["direction"]
    elif change >= 0.18:
        direction = "bearish"
    else:
        direction = "neutral"

    # Confidence grows with the amount of changed material and an LLM second
    # opinion; capped so a single noisy diff never dominates conviction.
    material = min(1.0, (score_obj.get("n_added", 0) + score_obj.get("n_removed", 0)) / 6.0)
    confidence = min(0.9, 0.35 + 0.3 * material + (0.2 if llm_categorization else 0.0))

    detail = {
        "section": section,
        "cosine_similarity": score_obj.get("cosine_similarity"),
        "jaccard_similarity": score_obj.get("jaccard_similarity"),
        "magnitude_bucket": bucket,
        "n_added": score_obj.get("n_added", 0),
        "n_removed": score_obj.get("n_removed", 0),
        "accession": accession,
    }
    if llm_categorization:
        detail["categories"] = llm_categorization.get("categories", [])
        detail["summary"] = llm_categorization.get("summary", "")
        detail["notable_changes"] = llm_categorization.get("notable_changes", [])

    sig = NLPSignal(
        ticker=ticker,
        signal_name="filing_change",
        value=change,
        direction=direction,
        confidence=round(confidence, 4),
        evidence_ids=evidence_ids,
        model="tfidf+jaccard" + ("+haiku" if llm_categorization else ""),
        detail=detail,
    )
    return sig, receipts
