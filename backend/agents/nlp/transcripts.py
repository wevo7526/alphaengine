"""
Earnings-call transcript NLP (Build Plan §2.2) — Firecrawl-only.

Extracts management tone, hedging/uncertainty density, Q&A evasiveness, and
(when a prior call is available) the tone delta vs. the previous call. Output
is a typed `call_tone` NLPSignal plus source receipts for the passages the
score is derived from. No sec-api involvement — the fetch runs entirely on
Firecrawl, offloading load from the scarce sec-api quota.

The scoring core is deterministic and testable on fixtures; the fetch is
injectable.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z']+")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Hedging / uncertainty lexicon — density rises when management is cagey.
_HEDGING = {
    "may", "might", "could", "would", "possibly", "perhaps", "potentially",
    "uncertain", "uncertainty", "unclear", "challenging", "challenges",
    "headwind", "headwinds", "difficult", "depends", "cautious", "caution",
    "volatile", "volatility", "pressure", "pressures", "soft", "softness",
    "macro", "weakness", "weaker", "slowdown", "choppy", "murky", "fluid",
}
# Q&A non-answers — evasiveness markers.
_EVASIVE = [
    "we don't provide guidance", "we do not provide guidance",
    "can't comment", "cannot comment", "won't comment", "not going to comment",
    "as i said", "as i mentioned", "too early to say", "we'll see",
    "i won't get into", "not going to break that out", "don't want to get ahead",
    "stay tuned", "more to come on that",
]


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall((text or "").lower())


def score_transcript(text: str) -> dict:
    """Deterministic transcript metrics. No network, no LLM.

    Returns {tone, hedging_density, uncertainty, evasiveness, n_words,
             hedged_sentences[]} where tone ∈ [-1,1], the rest ∈ [0,1].
    """
    from agents.nlp.sentiment import score_text

    toks = _tokens(text)
    n = len(toks)
    if n < 50:
        return {"tone": 0.0, "hedging_density": 0.0, "uncertainty": 0.0,
                "evasiveness": 0.0, "n_words": n, "hedged_sentences": [], "note": "too short"}

    hedge_count = sum(1 for t in toks if t in _HEDGING)
    hedging_density = hedge_count / n
    # Scale density to [0,1]: ~4% hedging words is already very cagey.
    uncertainty = min(1.0, hedging_density / 0.04)

    low = (text or "").lower()
    evasive_hits = sum(low.count(p) for p in _EVASIVE)
    # ~1 evasive marker per 400 words saturates the score.
    evasiveness = min(1.0, evasive_hits / max(1.0, n / 400.0))

    tone = float(score_text(text).get("compound", 0.0))

    # Surface the most-hedged sentences as candidate evidence passages.
    sents = [s.strip() for s in _SENT_SPLIT.split(text or "") if len(s.strip()) > 40]
    def _hedge_score(s: str) -> int:
        st = set(_tokens(s))
        return len(st & _HEDGING)
    hedged = sorted(sents, key=_hedge_score, reverse=True)
    hedged = [s for s in hedged if _hedge_score(s) > 0][:5]

    return {
        "tone": round(tone, 4),
        "hedging_density": round(hedging_density, 5),
        "uncertainty": round(uncertainty, 4),
        "evasiveness": round(evasiveness, 4),
        "n_words": n,
        "hedged_sentences": hedged,
    }


def build_call_tone_signal(
    ticker: str,
    current: dict,
    prior: dict | None = None,
    *,
    url: str | None = None,
):
    """Build a `call_tone` NLPSignal + source receipts from transcript scores.

    With a prior call, the signal is driven by the tone *delta* and the change
    in hedging/evasiveness (the leading-indicator read). Without one, it falls
    back to the absolute level at lower confidence. Returns (NLPSignal, receipts).
    """
    from agents.nlp.signals import NLPSignal
    from provenance import source_receipt

    receipts = []
    for s in (current.get("hedged_sentences") or [])[:4]:
        receipts.append(source_receipt(
            "firecrawl", url or f"transcript:{ticker}", s, ticker=ticker, url=url,
            label=f"earnings call (hedged) · {ticker}",
        ))
    evidence_ids = [r["content_hash"] for r in receipts]

    cur_tone = float(current.get("tone", 0.0))
    cur_unc = float(current.get("uncertainty", 0.0))
    cur_eva = float(current.get("evasiveness", 0.0))

    if prior:
        tone_delta = cur_tone - float(prior.get("tone", 0.0))
        unc_delta = cur_unc - float(prior.get("uncertainty", 0.0))
        # Improving tone + falling uncertainty = bullish; the reverse = bearish.
        composite = tone_delta - 0.5 * unc_delta - 0.3 * cur_eva
        value = min(1.0, abs(composite))
        if composite >= 0.08:
            direction = "bullish"
        elif composite <= -0.08:
            direction = "bearish"
        else:
            direction = "neutral"
        confidence = min(0.85, 0.4 + 0.45 * min(1.0, current.get("n_words", 0) / 4000.0))
        detail = {"mode": "delta", "tone_delta": round(tone_delta, 4),
                  "uncertainty_delta": round(unc_delta, 4), "evasiveness": cur_eva,
                  "tone": cur_tone, "prior_tone": prior.get("tone")}
    else:
        # Level-only read: confident negative tone or heavy hedging => bearish.
        composite = cur_tone - 0.5 * cur_unc - 0.3 * cur_eva
        value = min(1.0, abs(composite))
        if composite >= 0.15:
            direction = "bullish"
        elif composite <= -0.15:
            direction = "bearish"
        else:
            direction = "neutral"
        confidence = min(0.55, 0.25 + 0.3 * min(1.0, current.get("n_words", 0) / 4000.0))
        detail = {"mode": "level", "tone": cur_tone, "uncertainty": cur_unc,
                  "evasiveness": cur_eva}

    sig = NLPSignal(
        ticker=ticker, signal_name="call_tone", value=value, direction=direction,
        confidence=round(confidence, 4), evidence_ids=evidence_ids,
        model="vader+hedging", detail=detail,
    )
    return sig, receipts


async def fetch_transcript(ticker: str, *, firecrawl, quarter_hint: str = "") -> dict:
    """Best-effort: find + scrape the most recent earnings-call transcript.

    Returns {"text": str, "url": str|None}. Never raises.
    """
    try:
        q = f"{ticker} earnings call transcript {quarter_hint}".strip()
        results = await firecrawl.asearch_web(q, 3)
        for r in (results or []):
            url = r.get("url")
            if not url:
                continue
            doc = await firecrawl.ascrape_full(url)
            content = (doc or {}).get("content") or ""
            # A real transcript is long and mentions the call structure.
            if len(content) > 2000 and ("prepared remarks" in content.lower()
                                        or "question-and-answer" in content.lower()
                                        or "operator" in content.lower()):
                return {"text": content, "url": url}
        return {"text": "", "url": None}
    except Exception as e:  # noqa: BLE001
        logger.warning("[transcripts] fetch failed for %s: %s", ticker, e)
        return {"text": "", "url": None}


async def run_call_tone(
    ticker: str,
    *,
    firecrawl=None,
    evidence_repo=None,
    prior_scores: dict | None = None,
) -> dict:
    """Fetch + score the latest transcript → call_tone signal. Never raises.

    `prior_scores` is the previous call's `score_transcript` output (passed in
    by the caller, who persists it between quarters); when absent we use the
    level-only read.
    """
    from config import settings

    if not settings.TRANSCRIPT_NLP_ENABLED:
        return {"ticker": ticker, "signal": None, "receipts": [], "score": None,
                "warnings": ["transcript NLP disabled"]}

    if firecrawl is None:
        from data import firecrawl_client as firecrawl

    doc = await fetch_transcript(ticker, firecrawl=firecrawl)
    if not doc.get("text"):
        return {"ticker": ticker, "signal": None, "receipts": [], "score": None,
                "warnings": ["no transcript found"]}

    score = score_transcript(doc["text"])
    signal, receipts = build_call_tone_signal(ticker, score, prior_scores, url=doc.get("url"))
    return {"ticker": ticker, "signal": signal, "receipts": receipts,
            "score": score, "url": doc.get("url"), "warnings": []}
