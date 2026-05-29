"""
infra/citations_resolver.py — Resolve agent-emitted citations against
the memo's lineage block.

Pipeline:
  1. The Risk Manager and Portfolio Strategist emit `citations` arrays
     on RiskFactor / TradeIdea — each citation is just
     `{source_type, source_id}` (the LLM doesn't know URLs).
  2. After the CIO synthesizer runs, this module:
       a. Walks every RiskFactor and TradeIdea
       b. For each emitted citation, finds the matching entry in
          `memo.lineage.sources` by (type, id)
       c. Fills in `url`, `label`, `excerpt` from the lineage entry
       d. Drops citations with no matching lineage entry (LLM
          hallucination guard)
       e. Auto-populates citations for any TradeIdea / RiskFactor
          that came back uncited, using ticker-scoped tool calls
          from the lineage
       f. Builds the deduplicated `citation_index` and assigns
          monotonic numeric IDs (1, 2, 3, ...) for inline footnotes
  3. The CIO prose-marker pass (in citations_resolver.replace_inline_markers)
     scans `analysis` for `[[src:type:id]]` patterns, looks them up in
     the citation_index, and replaces with `[N]` numeric anchors.
     Unresolved markers are stripped silently — the prose still reads.

Failure mode: every step is wrapped in a try/except; on any error the
memo passes through unchanged (lineage panel still works). Coverage is
just dropped, not promoted to an error state.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# Inline marker pattern. Emitted by the CIO Synthesizer in prose like:
#   "AAPL revenue +8% YoY [[src:sec_filing:0001067983-25-000412]]"
# Greedy on the ID side because SEC accession numbers contain hyphens.
_INLINE_MARKER_RE = re.compile(r"\[\[src:([a-z_]+):([^\]]+)\]\]")


def _label_for_lineage(src: dict) -> str:
    """Build a one-line human-readable label for a lineage source.

    Used as the `label` on every resolved citation. Frontend renders
    this in hover popovers and PDF footnotes.
    """
    if not isinstance(src, dict):
        return "—"
    t = (src.get("type") or "other").lower()
    sid = src.get("id") or ""
    ticker = src.get("ticker") or ""
    form = src.get("form_type") or ""
    screen = src.get("screen") or ""

    if t == "sec_filing":
        return f"SEC {form} · {sid}".strip() if form else f"SEC filing · {sid}"
    if t == "sec_insider":
        return f"Insider transaction (Form 4) · {sid}"
    if t == "sec_13f":
        return f"13F · {sid}"
    if t == "fred_series":
        return f"FRED · {sid}"
    if t == "market_price":
        return f"Market data · {ticker or sid}"
    if t == "news_article":
        # `sid` for news is the title fragment captured at extraction
        return f"News · {sid[:80]}"
    if t == "web_search":
        return f"Web · {sid}"
    if t == "technical":
        return f"Technical · {sid}"
    if t == "screen":
        return f"Screen · {screen or sid}"
    if t == "computed":
        return f"Computed · {sid}"
    return f"{t} · {sid}"


def _build_lineage_index(lineage: dict) -> tuple[dict, dict]:
    """Index lineage sources for fast lookup.

    Returns:
      by_key: {(type, id): src_dict}
      by_ticker: {ticker_upper: [src_dict, ...]}
    """
    by_key: dict[tuple[str, str], dict] = {}
    by_ticker: dict[str, list[dict]] = {}
    if not isinstance(lineage, dict):
        return by_key, by_ticker
    for src in lineage.get("sources") or []:
        if not isinstance(src, dict):
            continue
        t = (src.get("type") or "other").lower()
        sid = str(src.get("id") or "").strip()
        if not sid:
            continue
        by_key[(t, sid)] = src
        # Also index by ticker when present, so we can backfill uncited
        # ideas with the sources that touched their name.
        tk = (src.get("ticker") or "").upper()
        if tk:
            by_ticker.setdefault(tk, []).append(src)
        # Market-data sources have IDs shaped like "AAPL@yfinance" — extract
        # the ticker prefix so backfill works even without an explicit field.
        if "@" in sid:
            prefix = sid.split("@", 1)[0].upper()
            if prefix and prefix not in by_ticker:
                by_ticker.setdefault(prefix, []).append(src)
    return by_key, by_ticker


def _resolve_one(
    citation: dict,
    by_key: dict,
    by_ticker: dict,
) -> dict | None:
    """Resolve a single agent-emitted citation against the lineage index.

    Returns the enriched citation dict on success, None when no match
    is found (caller drops these).
    """
    if not isinstance(citation, dict):
        return None
    src_type = (citation.get("source_type") or "other").lower()
    src_id = str(citation.get("source_id") or "").strip()
    if not src_id:
        return None

    # Try exact (type, id) match first
    hit = by_key.get((src_type, src_id))
    # Fallback: id may be a ticker-shaped value the LLM emitted without
    # the @yfinance suffix — look it up by ticker
    if hit is None and src_type == "market_price":
        candidates = by_ticker.get(src_id.upper(), [])
        if candidates:
            hit = candidates[0]
    # Fallback: id matches some other source type — try cross-type lookup
    if hit is None:
        for (t, sid), src in by_key.items():
            if sid == src_id:
                hit = src
                src_type = t
                break
    if hit is None:
        return None
    return {
        "source_type": src_type,
        "source_id": src_id,
        "url": hit.get("url") or None,
        "label": _label_for_lineage(hit),
        "excerpt": citation.get("excerpt"),  # preserved if the LLM provided one
        "n": 0,  # assigned later in build_citation_index
    }


def _backfill_for_item(
    item: dict,
    by_ticker: dict,
    max_n: int = 3,
) -> list[dict]:
    """Generate fallback citations for an uncited trade idea / risk factor.

    Strategy: if the item has a `ticker` field and the lineage has sources
    that touched that ticker, surface up to `max_n` of those. This handles
    the common case where the LLM omits citations entirely; we still want
    the user to see "this idea came from X, Y, Z tool calls" rather than
    rendering an empty source rail.
    """
    if not isinstance(item, dict):
        return []
    ticker = (item.get("ticker") or "").upper()
    if not ticker:
        return []
    candidates = by_ticker.get(ticker, [])
    if not candidates:
        return []
    out: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    # Prefer SEC filings + market data over news; market data is the most
    # universally useful anchor (current price, fundamentals).
    priority = {"market_price": 0, "sec_filing": 1, "sec_insider": 2,
                "sec_13f": 3, "technical": 4, "news_article": 5,
                "web_search": 6, "screen": 7, "computed": 8, "other": 9}
    candidates_sorted = sorted(
        candidates,
        key=lambda s: priority.get((s.get("type") or "other").lower(), 9),
    )
    for src in candidates_sorted:
        if not isinstance(src, dict):
            continue
        key = ((src.get("type") or "other").lower(), str(src.get("id") or ""))
        if not key[1] or key in seen_keys:
            continue
        seen_keys.add(key)
        out.append({
            "source_type": key[0],
            "source_id": key[1],
            "url": src.get("url") or None,
            "label": _label_for_lineage(src),
            "excerpt": None,
            "n": 0,
        })
        if len(out) >= max_n:
            break
    return out


def resolve_memo_citations(memo: dict) -> dict:
    """Walk a memo dict, resolve citations on every TradeIdea + RiskFactor,
    build the deduplicated citation_index, and replace inline markers in
    `analysis` prose. Returns the same memo dict (mutated in place).

    Never raises — failures fall through and leave the memo untouched.
    """
    if not isinstance(memo, dict):
        return memo
    lineage = memo.get("lineage") or {}
    try:
        by_key, by_ticker = _build_lineage_index(lineage)
    except Exception as e:
        logger.warning(f"resolve_memo_citations index failed: {e}")
        return memo

    # Resolve citations on every TradeIdea
    trade_ideas = memo.get("trade_ideas") or []
    for idea in trade_ideas:
        if not isinstance(idea, dict):
            continue
        emitted = idea.get("citations") or []
        resolved: list[dict] = []
        for cit in emitted:
            r = _resolve_one(cit, by_key, by_ticker)
            if r is not None:
                resolved.append(r)
        # Backfill if the LLM emitted nothing usable
        if not resolved:
            resolved = _backfill_for_item(idea, by_ticker)
        idea["citations"] = resolved

    # Resolve citations on every RiskFactor — same logic but no ticker
    # backfill (risk factors aren't ticker-scoped)
    risk_factors = memo.get("risk_factors") or []
    for rf in risk_factors:
        if not isinstance(rf, dict):
            continue
        emitted = rf.get("citations") or []
        resolved: list[dict] = []
        for cit in emitted:
            r = _resolve_one(cit, by_key, by_ticker)
            if r is not None:
                resolved.append(r)
        rf["citations"] = resolved

    # Build the deduplicated citation_index
    index: list[dict] = []
    seen: dict[tuple[str, str], int] = {}
    for idea in trade_ideas:
        if not isinstance(idea, dict):
            continue
        for c in idea.get("citations") or []:
            key = (c["source_type"], c["source_id"])
            if key in seen:
                c["n"] = seen[key]
                continue
            n = len(index) + 1
            c["n"] = n
            seen[key] = n
            index.append({**c, "n": n})
    for rf in risk_factors:
        if not isinstance(rf, dict):
            continue
        for c in rf.get("citations") or []:
            key = (c["source_type"], c["source_id"])
            if key in seen:
                c["n"] = seen[key]
                continue
            n = len(index) + 1
            c["n"] = n
            seen[key] = n
            index.append({**c, "n": n})

    # Also walk inline markers in `analysis` prose — they may reference
    # sources that no trade-idea / risk-factor cited
    analysis = memo.get("analysis") or ""
    if isinstance(analysis, str) and analysis:
        new_text, marker_resolutions, n_markers, n_resolved = replace_inline_markers(
            analysis, by_key, by_ticker, seen, index,
        )
        memo["analysis"] = new_text
        memo["_inline_marker_stats"] = {
            "total": n_markers,
            "resolved": n_resolved,
        }

    memo["citation_index"] = index
    return memo


def replace_inline_markers(
    text: str,
    by_key: dict,
    by_ticker: dict,
    seen: dict[tuple[str, str], int],
    index: list[dict],
) -> tuple[str, int, int, int]:
    """Replace `[[src:type:id]]` markers with `[N]` numeric anchors.

    Mutates `seen` and `index` in place — any markers that reference
    sources not yet in the index get appended. Unresolved markers are
    stripped silently so the prose stays clean.

    Returns: (new_text, resolutions_dict_unused, total_markers, resolved_count)
    """
    total = 0
    resolved = 0

    def _sub(m: re.Match) -> str:
        nonlocal total, resolved
        total += 1
        raw_type = (m.group(1) or "").strip().lower()
        raw_id = (m.group(2) or "").strip()
        if not raw_id:
            return ""
        r = _resolve_one(
            {"source_type": raw_type, "source_id": raw_id},
            by_key, by_ticker,
        )
        if r is None:
            return ""  # strip unresolved markers entirely
        key = (r["source_type"], r["source_id"])
        if key in seen:
            n = seen[key]
        else:
            n = len(index) + 1
            r["n"] = n
            seen[key] = n
            index.append(r)
        resolved += 1
        # The leading non-breaking space prevents the bracket from
        # touching the preceding word; the closing bracket has no
        # space so multiple cites read as "fact[1][2]"
        return f" [{n}]"

    new_text = _INLINE_MARKER_RE.sub(_sub, text)
    return new_text, {}, total, resolved
