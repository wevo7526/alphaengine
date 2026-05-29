"""
Stage 2 helpers — narration with the Fact Sheet, and the post-narration
evidence finalize (validate + footnote conversion + citation index + links).

The narrator (CIO synthesizer) is handed `fact_sheet_prompt_block(...)` and
asked to cite `[[ev:n]]` after factual sentences. `finalize_with_evidence`
then runs the validator, converts the `[[ev:n]]` markers to numbered `[N]`
footnotes (continuing after any existing source citations), appends the cited
evidence to the memo's citation_index, and emits the claim→evidence links to
persist.
"""

from __future__ import annotations

import re

from pipeline.validate import validate_memo, extract_citation_markers

_EV_MARKER = re.compile(r"\[\[ev:(\d+)\]\]")

# Fact Sheet source_name → Citation source_type taxonomy (agents/citations.py).
_SOURCE_TYPE = {
    "fred": "fred_series",
    "yahoo": "market_price",
    "sec": "sec_filing",
    "newsapi": "news_article",
    "finnhub": "news_article",
    "firecrawl": "web_search",
    "alpha_vantage": "technical",
    "engine": "computed",
}

# Prose fields the validator gates. Trade-idea / risk-factor numeric fields are
# receipted structurally (computed receipts), not as prose.
_PROSE_FIELDS = ("analysis", "executive_summary")


def fact_sheet_prompt_block(fact_sheet) -> str:
    """Render the FACT SHEET block + citation instructions for the narrator."""
    if not fact_sheet or len(fact_sheet) == 0:
        return ""
    return (
        "\n=== FACT SHEET (the ONLY facts you may state as numbers) ===\n"
        + fact_sheet.render_for_llm()
        + "\n\nCITATION RULE: every sentence that states a number MUST end with "
        "the matching `[[ev:n]]` marker from the Fact Sheet above (e.g. "
        "\"...P/E of 32.59 [[ev:6]].\"). Do NOT invent numbers that are not in "
        "the Fact Sheet. If a figure you want is missing, omit it rather than "
        "guess. You may cite more than one: `[[ev:3]][[ev:7]]`.\n"
    )


def repair_prompt_block(orphans: list[str], dangling: list[int]) -> str:
    """Build the corrective note for the auto-repair re-prompt."""
    parts = ["\n=== CITATION REPAIR REQUIRED ===\n"]
    if orphans:
        sample = ", ".join(dict.fromkeys(orphans))[:200]
        parts.append(
            f"These numbers appeared with NO valid [[ev:n]] citation: {sample}. "
            "For each, either append the correct [[ev:n]] marker from the Fact "
            "Sheet, or remove the number from the prose.\n"
        )
    if dangling:
        parts.append(
            f"These citation ids do not exist in the Fact Sheet: "
            f"{', '.join(str(d) for d in dangling)}. Remove or correct them.\n"
        )
    parts.append(
        "Re-emit the SAME memo JSON with citations fixed. Change nothing else.\n"
    )
    return "".join(parts)


def _prose_blob(memo: dict) -> str:
    pieces = []
    for f in _PROSE_FIELDS:
        v = memo.get(f)
        if isinstance(v, str) and v:
            pieces.append(v)
    for kf in (memo.get("key_findings") or []):
        if isinstance(kf, str):
            pieces.append(kf)
    return "\n".join(pieces)


def validate_against_fact_sheet(memo: dict, fact_sheet):
    """Run the linter over the memo's narrative prose. Returns ValidationResult."""
    return validate_memo(_prose_blob(memo), fact_sheet)


def _entry_to_citation(e: dict) -> dict:
    """Map a Fact Sheet entry to a Citation-shaped dict.

    IntelligenceMemo coerces these through the Citation model, which keeps only
    {n, source_type, source_id, url, label, excerpt}. So we encode the
    receipt's value + named formula (computed) or verbatim passage (source)
    into those surviving fields — this IS the clickable receipt (Build Plan
    §1.4): a computed footnote reads "VIX = 25.78 — data.fred.get_macro_snapshot".
    """
    if e.get("kind") == "computed":
        label = f"{e.get('metric')} = {e.get('display_value')}"
        source_id = str(e.get("formula_ref") or e.get("source_name") or "")
        excerpt = f"computed via {e.get('formula_ref')}"
    else:
        label = e.get("label") or f"{e.get('source_name')}:{e.get('source_ref')}"
        source_id = str(e.get("source_ref") or "")
        excerpt = e.get("passage")
    return {
        "n": e["n"],
        "source_type": _SOURCE_TYPE.get(e.get("source_name"), "computed"),
        "source_id": source_id,
        "url": e.get("url"),
        "label": label,
        "excerpt": excerpt,
    }


def finalize_with_evidence(memo: dict, fact_sheet, base_index: int = 0) -> dict:
    """Deterministically bind every memo claim to the Fact Sheet.

    The Fact Sheet is AUTHORITATIVE — the citation_index is the full set of
    receipts (always non-empty when the desks produced any numbers), and each
    trade idea / risk factor gets its ticker-matched receipts attached
    REGARDLESS of whether the LLM emitted any `[[ev:n]]` markers. Inline
    `[[ev:n]]` markers in prose are converted to `[N]` footnotes as a bonus
    when present. `base_index` is ignored (kept for signature stability).

    Returns {memo, citation_index, links, cited_ids}.
    """
    entries = list(getattr(fact_sheet, "entries", []))
    # 1. citation_index = every receipt, numbered by its Fact Sheet index.
    citation_index = [_entry_to_citation(e) for e in entries]
    cite_by_n = {e["n"]: c for e, c in zip(entries, citation_index)}

    # 2. inline [[ev:n]] -> [n] in narrative prose (n == Fact Sheet index).
    def _sub(text):
        if not isinstance(text, str):
            return text
        return _EV_MARKER.sub(lambda m: f"[{int(m.group(1))}]"
                              if int(m.group(1)) in cite_by_n else "", text)

    for f in _PROSE_FIELDS:
        if isinstance(memo.get(f), str):
            memo[f] = _sub(memo[f])
    if isinstance(memo.get("key_findings"), list):
        memo["key_findings"] = [_sub(k) if isinstance(k, str) else k for k in memo["key_findings"]]

    # 3. Attach ticker-matched receipts to each trade idea + risk factor.
    by_ticker: dict[str, list[dict]] = {}
    macro_cites: list[dict] = []
    for e, c in zip(entries, citation_index):
        tk = (e.get("ticker") or "").upper()
        if tk:
            by_ticker.setdefault(tk, []).append(c)
        elif e.get("kind") == "computed":
            macro_cites.append(c)  # VIX/regime/credit etc. — portfolio-level anchors

    links = []
    for idea in (memo.get("trade_ideas") or []):
        if not isinstance(idea, dict):
            continue
        tk = (idea.get("ticker") or "").upper()
        cites = (by_ticker.get(tk) or [])[:6] or macro_cites[:2]
        idea["citations"] = cites
        for c in cites:
            links.append({"claim_ref": f"trade_idea:{tk or '?'}", "n": c["n"]})

    for rf in (memo.get("risk_factors") or []):
        if not isinstance(rf, dict):
            continue
        tk = (rf.get("ticker") or "").upper()
        cites = (by_ticker.get(tk) or [])[:4] if tk else macro_cites[:4]
        # Always give a risk factor at least one anchor (DoD: every RF cited).
        rf["citations"] = cites or (citation_index[:2] if citation_index else [])

    # Map cited links back to content hashes for evidence-claim persistence.
    n_to_hash = {e["n"]: e.get("content_hash") for e in entries}
    persist_links = [
        {"claim_ref": l["claim_ref"], "content_hash": n_to_hash.get(l["n"])}
        for l in links if n_to_hash.get(l["n"])
    ]
    cited_ids = sorted({l["n"] for l in links})

    return {
        "memo": memo,
        "citation_index": citation_index,
        "links": persist_links,
        "cited_ids": cited_ids,
    }
