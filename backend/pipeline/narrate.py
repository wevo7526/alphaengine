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


def finalize_with_evidence(memo: dict, fact_sheet, base_index: int = 0) -> dict:
    """Convert evidence markers to footnotes, extend citation_index, build links.

    `base_index` is the count of existing (source-citation) footnotes so the
    evidence footnotes continue the numbering rather than collide. Returns:
        {
          "memo": memo (analysis/exec-summary markers rewritten to [N]),
          "citation_additions": [Citation-shaped dicts],
          "links": [{"claim_ref", "content_hash"}],
          "cited_ids": [n,...],          # evidence ids actually cited
        }
    """
    cited_in_prose = set()
    for f in _PROSE_FIELDS:
        v = memo.get(f)
        if isinstance(v, str):
            cited_in_prose.update(extract_citation_markers(v))

    # Global footnote number for each cited evidence id.
    def globalnum(n: int) -> int:
        return base_index + n

    def _sub(text: str) -> str:
        if not isinstance(text, str):
            return text
        return _EV_MARKER.sub(lambda m: f"[{globalnum(int(m.group(1)))}]", text)

    for f in _PROSE_FIELDS:
        if isinstance(memo.get(f), str):
            memo[f] = _sub(memo[f])
    if isinstance(memo.get("key_findings"), list):
        memo["key_findings"] = [_sub(k) if isinstance(k, str) else k for k in memo["key_findings"]]

    # Build citation_index additions + claim links for every cited entry.
    citation_additions = []
    links = []
    cited_ids = sorted(i for i in cited_in_prose if fact_sheet.get(i))
    for n in cited_ids:
        e = fact_sheet.get(n)
        if not e:
            continue
        gnum = globalnum(n)
        # IntelligenceMemo coerces these dicts through the Citation model,
        # which keeps only {n, source_type, source_id, url, label, excerpt}.
        # So encode the receipt's value + named formula + timestamp into those
        # surviving fields — this IS the clickable "receipt" (Build Plan §1.4):
        # a computed footnote reads "VIX = 25.78 — data.fred.get_macro_snapshot",
        # a source footnote carries the verbatim passage as its excerpt.
        if e.get("kind") == "computed":
            label = f"{e.get('metric')} = {e.get('display_value')}"
            source_id = str(e.get("formula_ref") or e.get("source_name") or "")
            excerpt = f"computed via {e.get('formula_ref')} @ {e.get('retrieved_at')}"
        else:
            label = e.get("label")
            source_id = str(e.get("source_ref") or "")
            excerpt = e.get("passage")
        citation_additions.append({
            "n": gnum,
            "source_type": _SOURCE_TYPE.get(e.get("source_name"), "computed"),
            "source_id": source_id,
            "url": e.get("url"),
            "label": label,
            "excerpt": excerpt,
        })
        links.append({
            "claim_ref": f"analysis:ev:{gnum}",
            "content_hash": e.get("content_hash"),
        })

    return {
        "memo": memo,
        "citation_additions": citation_additions,
        "links": links,
        "cited_ids": cited_ids,
    }
