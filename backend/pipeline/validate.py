"""
Stage 3 — the citation linter (hard gate).

Parses generated memo prose and verifies every factual claim traces to a
Fact Sheet entry:

  - **orphan**  : a numeric token in a sentence carrying NO `[[ev:n]]` citation,
                  whose value also matches no Fact Sheet entry. This HARD-FAILS
                  the memo (Build Plan §1.3).
  - **dangling**: a `[[ev:n]]` citation whose `n` is not a real Fact Sheet
                  entry (LLM invented the receipt id). Also a hard fail.
  - **mismatch**: a cited number that doesn't match the value of any evidence
                  cited in its sentence. Reported as a warning, not a hard fail
                  (the number may be a legitimate derived figure like a sum).

The numeric extraction mirrors base_agent._ground_check so the soft tripwire
and the hard gate agree on what counts as a "number."
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# Numbers up to 7 digits with optional commas and ≤4 decimals, or plain decimals.
_NUM_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+(?:\.\d{1,4})?|-?\d+(?:\.\d{1,4})?")
# `[[ev:12]]` citation markers.
_CITE_RE = re.compile(r"\[\[ev:(\d+)\]\]")
# Generic integers that show up as list numbering / round references, not claims.
_GENERIC = {0, 1, 2, 3, 5, 10, 100}
# Sentence splitter — keep it cheap; financial prose is well-punctuated.
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def extract_citation_markers(text: str) -> list[int]:
    """Return every `[[ev:n]]` id referenced in the text (with repeats)."""
    return [int(m) for m in _CITE_RE.findall(text or "")]


def _to_float(tok: str) -> float | None:
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def extract_numeric_tokens(text: str, skip_generic: bool = True) -> list[str]:
    """Extract candidate numeric claim tokens, skipping citation ids and generics.

    Citation markers `[[ev:7]]` are stripped first so their ids are never
    mistaken for claims.
    """
    if not text:
        return []
    stripped = _CITE_RE.sub(" ", text)
    out: list[str] = []
    for tok in _NUM_RE.findall(stripped):
        val = _to_float(tok)
        if val is None:
            continue
        if skip_generic and val in _GENERIC:
            continue
        out.append(tok)
    return out


def _matches_any_value(val: float, entries: list[dict]) -> bool:
    """True if `val` matches a computed entry's value or appears in a source passage."""
    if abs(val) >= 50:
        tol = max(0.05, abs(val) * 0.01)
    else:
        tol = max(0.05, abs(val) * 0.02)
    for e in entries:
        if e.get("kind") == "computed":
            ev = e.get("value")
            if isinstance(ev, bool):
                continue
            if isinstance(ev, (int, float)) and math.isfinite(ev):
                if abs(float(ev) - val) <= tol:
                    return True
            # numbers embedded in the display string
            disp = str(e.get("display_value", ""))
            for s in {f"{val:.0f}", f"{val:.1f}", f"{val:.2f}"}:
                if s and s in disp:
                    return True
        else:  # source — number must appear in the verbatim passage
            psg = e.get("passage") or ""
            for s in {f"{val:.0f}", f"{val:.1f}", f"{val:.2f}"}:
                if s and s in psg:
                    return True
    return False


@dataclass
class ValidationResult:
    ok: bool
    orphans: list[str] = field(default_factory=list)        # uncited, unmatched numbers
    dangling: list[int] = field(default_factory=list)       # citations to nonexistent evidence
    mismatches: list[str] = field(default_factory=list)     # cited but value mismatch (warning)
    numeric_claims: int = 0
    cited_sentences: int = 0
    total_sentences: int = 0

    def summary(self) -> str:
        return (
            f"ok={self.ok} orphans={len(self.orphans)} dangling={len(self.dangling)} "
            f"mismatches={len(self.mismatches)} numeric_claims={self.numeric_claims} "
            f"sentences={self.cited_sentences}/{self.total_sentences}"
        )


def validate_memo(prose: str, fact_sheet) -> ValidationResult:
    """Lint memo prose against a FactSheet (or any object exposing
    `valid_ids: set[int]`, `get(n)->entry`, and `entries: list[dict]`).

    Hard-fails (ok=False) when any orphan numeric token or any dangling
    citation exists.
    """
    prose = prose or ""
    valid_ids = set(getattr(fact_sheet, "valid_ids", set()))
    all_entries = list(getattr(fact_sheet, "entries", []))
    get_entry = getattr(fact_sheet, "get", lambda n: None)

    # 1. Dangling citations across the whole prose.
    dangling = sorted({n for n in extract_citation_markers(prose) if n not in valid_ids})

    orphans: list[str] = []
    mismatches: list[str] = []
    numeric_claims = 0
    cited_sentences = 0
    sentences = [s for s in _SENT_SPLIT.split(prose) if s.strip()]

    for sent in sentences:
        cite_ids = [n for n in extract_citation_markers(sent) if n in valid_ids]
        if cite_ids:
            cited_sentences += 1
        cited_entries = [get_entry(n) for n in cite_ids]
        cited_entries = [e for e in cited_entries if e]
        for tok in extract_numeric_tokens(sent):
            numeric_claims += 1
            val = _to_float(tok)
            if val is None:
                continue
            if not cite_ids:
                # No citation in this sentence. Allowed only if the value is
                # itself present somewhere in the Fact Sheet (e.g. an obvious
                # restatement); otherwise it's an orphan and hard-fails.
                if not _matches_any_value(val, all_entries):
                    orphans.append(tok)
                continue
            # Cited: the cited evidence should support the number.
            if not _matches_any_value(val, cited_entries):
                mismatches.append(tok)

    ok = not orphans and not dangling
    return ValidationResult(
        ok=ok,
        orphans=orphans,
        dangling=dangling,
        mismatches=mismatches,
        numeric_claims=numeric_claims,
        cited_sentences=cited_sentences,
        total_sentences=len(sentences),
    )
