"""
infra/coverage.py — Citation coverage gate for memos.

Computes two coverage numbers after the citations_resolver finishes:

  citation_coverage_pct
      % of (trade_ideas + risk_factors) that carry ≥1 resolved citation.
      Measures whether the structured outputs are anchored to lineage.

  claim_coverage_pct
      # inline `[N]` markers in `analysis` prose / # numerical tokens.
      Loose proxy: a "numerical token" is any digit run with optional
      decimal/percent. Measures whether the prose claims are anchored.

Combines into verification_status:
    verified    — both ≥ 80
    partial     — one ≥ 50 OR both 50–79
    unverified  — anything else (default fallback)

Failure-safe: returns the default "unverified" stub on any error.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


_NUMERIC_TOKEN_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?%?\b")
_INLINE_ANCHOR_RE = re.compile(r"\[\d+\]")


def _default_coverage() -> dict:
    return {
        "citation_coverage_pct": 0,
        "claim_coverage_pct": 0,
        "trade_ideas_cited": 0,
        "trade_ideas_total": 0,
        "risk_factors_cited": 0,
        "risk_factors_total": 0,
        "numeric_claims": 0,
        "inline_anchors": 0,
    }


def compute_coverage(memo: dict) -> dict:
    """Compute citation + claim coverage for a memo. Returns a stats dict.

    The resolver must have already run — this function reads the resolved
    `citations` lists on trade_ideas / risk_factors and counts `[N]`
    anchors in `analysis`.
    """
    try:
        stats = _default_coverage()
        trade_ideas = memo.get("trade_ideas") or []
        risk_factors = memo.get("risk_factors") or []

        n_ideas = sum(1 for x in trade_ideas if isinstance(x, dict))
        n_risks = sum(1 for x in risk_factors if isinstance(x, dict))
        ideas_cited = sum(
            1 for x in trade_ideas
            if isinstance(x, dict) and len(x.get("citations") or []) > 0
        )
        risks_cited = sum(
            1 for x in risk_factors
            if isinstance(x, dict) and len(x.get("citations") or []) > 0
        )
        total_items = n_ideas + n_risks
        total_cited = ideas_cited + risks_cited
        citation_coverage_pct = round(
            (total_cited / total_items * 100) if total_items > 0 else 0,
            1,
        )

        analysis = memo.get("analysis") or ""
        numeric_tokens = len(_NUMERIC_TOKEN_RE.findall(analysis)) if isinstance(analysis, str) else 0
        inline_anchors = len(_INLINE_ANCHOR_RE.findall(analysis)) if isinstance(analysis, str) else 0
        # Cap at 100 — a paragraph can carry multiple anchors per claim
        claim_coverage_pct = round(
            min(100, (inline_anchors / numeric_tokens * 100)) if numeric_tokens > 0 else 0,
            1,
        )

        stats.update({
            "citation_coverage_pct": citation_coverage_pct,
            "claim_coverage_pct": claim_coverage_pct,
            "trade_ideas_cited": ideas_cited,
            "trade_ideas_total": n_ideas,
            "risk_factors_cited": risks_cited,
            "risk_factors_total": n_risks,
            "numeric_claims": numeric_tokens,
            "inline_anchors": inline_anchors,
        })
        return stats
    except Exception as e:
        logger.warning(f"compute_coverage failed (non-fatal): {e}")
        return _default_coverage()


def grade_verification(coverage: dict) -> str:
    """Map a coverage stats dict to a verification_status string.

    Tiers:
      verified    — citation_coverage ≥ 80 AND claim_coverage ≥ 80
                     (or no numeric claims to cite AND citation ≥ 80)
      partial     — either is ≥ 50, or both are in 50–79
      unverified  — anything else
    """
    try:
        cit = float(coverage.get("citation_coverage_pct") or 0)
        claim = float(coverage.get("claim_coverage_pct") or 0)
        n_claims = int(coverage.get("numeric_claims") or 0)
        # Special case: a memo with no numeric prose claims can still be
        # "verified" if every trade idea + risk factor is cited.
        if n_claims == 0:
            if cit >= 80:
                return "verified"
            if cit >= 50:
                return "partial"
            return "unverified"
        if cit >= 80 and claim >= 80:
            return "verified"
        if cit >= 50 or claim >= 50:
            return "partial"
        return "unverified"
    except Exception:
        return "unverified"
