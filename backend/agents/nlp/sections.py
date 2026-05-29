"""
10-K / 10-Q section extraction from raw filing text/markdown (Build Plan §2.1b).

When we scrape a filing's public HTML via Firecrawl we get the *whole*
document as markdown, not sec-api's pre-extracted section. This parser pulls
out the sections that carry the documented text signal — Risk Factors
(Item 1A) and MD&A (Item 7 for 10-K, Item 2 for 10-Q) — using item-heading
anchors.

Pure and deterministic — fully testable on fixtures, no network. The ingest
layer falls back to sec-api's ExtractorApi only when this returns nothing.
"""

from __future__ import annotations

import re

# Strip markdown emphasis / links so heading anchors match cleanly.
_MD_NOISE = re.compile(r"[*_`>#]+")


def _clean(text: str) -> str:
    # Collapse markdown emphasis and excess whitespace but KEEP newlines as
    # spaces so item headings split on a single line are still matched.
    t = _MD_NOISE.sub(" ", text or "")
    return t


# (start_pattern, [end_patterns]) per logical section. Patterns are
# case-insensitive and tolerate ".", ")", ":", "-", and whitespace between
# the item number and the title.
_SEP = r"[.\)\:\-—\s]+"
_SECTION_ANCHORS: dict[str, dict] = {
    # 10-K Risk Factors
    "1A": {
        "start": rf"item{_SEP}1a{_SEP}risk\s+factors",
        "end": [rf"item{_SEP}1b{_SEP}", rf"item{_SEP}2{_SEP}propert"],
    },
    # 10-K MD&A
    "7": {
        "start": rf"item{_SEP}7{_SEP}management.s\s+discussion",
        "end": [rf"item{_SEP}7a{_SEP}", rf"item{_SEP}8{_SEP}financial\s+statements"],
    },
    # 10-Q MD&A (Part I, Item 2)
    "2": {
        "start": rf"item{_SEP}2{_SEP}management.s\s+discussion",
        "end": [rf"item{_SEP}3{_SEP}quantitative", rf"item{_SEP}4{_SEP}controls"],
    },
}

# A real section body is meaningfully longer than a table-of-contents line.
_MIN_SECTION_CHARS = 400


def extract_section_from_text(text: str, section: str = "1A") -> str:
    """Extract one filing section from full document text/markdown.

    Returns "" when the section can't be located (caller should fall back to
    sec-api). Picks the LONGEST start→end span so the table-of-contents entry
    (a short span between two adjacent headings) is naturally skipped.
    """
    anchors = _SECTION_ANCHORS.get(section)
    if not anchors or not text:
        return ""
    cleaned = _clean(text)
    starts = [m.start() for m in re.finditer(anchors["start"], cleaned, re.IGNORECASE)]
    if not starts:
        return ""
    end_positions: list[int] = []
    for pat in anchors["end"]:
        end_positions.extend(m.start() for m in re.finditer(pat, cleaned, re.IGNORECASE))
    end_positions.sort()

    best = ""
    for s in starts:
        # First end anchor strictly after this start; else end of document.
        nxt = next((e for e in end_positions if e > s + 40), len(cleaned))
        body = cleaned[s:nxt].strip()
        if len(body) > len(best):
            best = body
    return best if len(best) >= _MIN_SECTION_CHARS else ""


def best_effort_sections(text: str, form_type: str = "10-K") -> dict:
    """Extract the standard signal-bearing sections for a filing.

    Returns {"risk_factors": str, "mda": str} — empty strings when missing.
    """
    risk = extract_section_from_text(text, "1A")
    if form_type.upper().startswith("10-Q"):
        mda = extract_section_from_text(text, "2") or extract_section_from_text(text, "7")
    else:
        mda = extract_section_from_text(text, "7")
    return {"risk_factors": risk, "mda": mda}
