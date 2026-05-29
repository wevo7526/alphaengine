"""
Evidence receipts + the in-memory Fact Sheet.

Receipts are plain dicts (DB-ready and JSON-serializable) so the compute
stage can build them with zero DB coupling; the FactSheet collects them,
deduplicates by content hash, and assigns each a stable per-memo index `n`
that the narration LLM cites as `[[ev:n]]`.

Determinism contract (Build Plan Verification): identical inputs produce an
identical `content_hash`. Floats are canonicalized to 12 significant figures
before hashing so harmless float jitter (e.g. 0.30000000000000004) does not
fork a receipt into two rows.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

# Recognized source names — keep in step with infra/lineage SOURCE_TYPES so
# receipts and the legacy lineage block speak the same vocabulary.
SOURCE_NAMES = {
    "fred", "yahoo", "sec", "newsapi", "finnhub", "alpha_vantage",
    "firecrawl", "engine",
}


def _canonicalize(obj: Any) -> Any:
    """Recursively normalize a value for stable hashing.

    - floats rounded to 12 significant figures (kills float jitter)
    - dict keys sorted (handled by json.dumps sort_keys at the end)
    - NaN/inf collapsed to None (they are not JSON-stable)
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        if obj == 0:
            return 0.0
        # 12 significant figures
        digits = 12 - int(math.floor(math.log10(abs(obj)))) - 1
        return round(obj, max(0, digits))
    if isinstance(obj, dict):
        return {str(k): _canonicalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(v) for v in obj]
    return obj


def content_hash(*parts: Any) -> str:
    """Stable SHA-256 over the canonicalized parts. Order-significant."""
    canon = _canonicalize(list(parts))
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_value(value: Any) -> str:
    """Human-readable one-line rendering of a computed value for the Fact Sheet."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "n/a"
        # Trim trailing zeros but keep up to 4 decimals.
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if isinstance(value, (int, str)):
        return str(value)
    return json.dumps(value, default=str)[:120]


def computed_receipt(
    metric: str,
    value: Any,
    *,
    formula_ref: str,
    inputs: Any = None,
    source_name: str = "engine",
    source_ref: str | None = None,
    ticker: str | None = None,
    label: str | None = None,
) -> dict:
    """Build a computed receipt for a number the engine produced.

    `formula_ref` should name the function that produced it, e.g.
    "quant.risk.parametric_var" — this is the auditable "named formula" the
    Build Plan DoD requires on every trade-idea field.
    """
    h = content_hash("computed", metric, formula_ref, inputs, value)
    return {
        "kind": "computed",
        "source_name": source_name,
        "source_ref": source_ref or formula_ref,
        "passage": None,
        "metric": metric,
        "value": value,
        "inputs": inputs,
        "formula_ref": formula_ref,
        "ticker": (ticker or None),
        "content_hash": h,
        "label": label or metric,
        "display_value": _fmt_value(value),
        "retrieved_at": _now_iso(),
    }


def source_receipt(
    source_name: str,
    source_ref: str,
    passage: str,
    *,
    ticker: str | None = None,
    label: str | None = None,
    url: str | None = None,
) -> dict:
    """Build a source receipt grounding a qualitative claim in retrieved text.

    The passage is stored verbatim (callers should keep it to a few sentences).
    The content hash is over (source_name, source_ref, normalized passage) so a
    re-fetch of the same passage upserts to the same row — this is the
    content-hash cache that avoids duplicate paid calls.
    """
    norm_passage = " ".join((passage or "").split())
    h = content_hash("source", source_name, source_ref, norm_passage)
    return {
        "kind": "source",
        "source_name": source_name,
        "source_ref": source_ref,
        "url": url or (source_ref if str(source_ref).startswith("http") else None),
        "passage": norm_passage,
        "metric": None,
        "value": None,
        "inputs": None,
        "formula_ref": None,
        "ticker": (ticker or None),
        "content_hash": h,
        "label": label or f"{source_name}:{source_ref}",
        "display_value": (norm_passage[:80] + "…") if len(norm_passage) > 80 else norm_passage,
        "retrieved_at": _now_iso(),
    }


class FactSheet:
    """Ordered, deduplicated collection of receipts for one memo.

    Each unique receipt (by content_hash) gets a stable 1-based index `n`.
    The narration LLM is shown the Fact Sheet and cites entries as `[[ev:n]]`;
    the validator checks every cited `n` exists and every number in the prose
    maps to a cited entry.
    """

    def __init__(self) -> None:
        self._entries: list[dict] = []
        self._by_hash: dict[str, dict] = {}

    def add(self, receipt: dict) -> int:
        """Add a receipt, returning its index `n`. Idempotent by content_hash."""
        h = receipt.get("content_hash")
        if not h:
            raise ValueError("receipt missing content_hash — build via computed_receipt/source_receipt")
        existing = self._by_hash.get(h)
        if existing is not None:
            return existing["n"]
        n = len(self._entries) + 1
        entry = dict(receipt)
        entry["n"] = n
        self._entries.append(entry)
        self._by_hash[h] = entry
        return n

    def add_many(self, receipts: list[dict]) -> list[int]:
        return [self.add(r) for r in receipts if r]

    def get(self, n: int) -> dict | None:
        if 1 <= n <= len(self._entries):
            return self._entries[n - 1]
        return None

    @property
    def entries(self) -> list[dict]:
        return list(self._entries)

    @property
    def valid_ids(self) -> set[int]:
        return {e["n"] for e in self._entries}

    def __len__(self) -> int:
        return len(self._entries)

    def render_for_llm(self, max_passage: int = 280) -> str:
        """Render the Fact Sheet as the factual context block for narration.

        Compact, one line per entry, with the `[[ev:n]]` token the LLM must
        echo. Computed entries show metric=value; source entries show the
        passage (truncated) and its origin.
        """
        if not self._entries:
            return "(no facts available)"
        lines = []
        for e in self._entries:
            tag = f"[[ev:{e['n']}]]"
            tk = f" {e['ticker']}" if e.get("ticker") else ""
            if e["kind"] == "computed":
                lines.append(
                    f"{tag}{tk} {e['metric']} = {e['display_value']} "
                    f"(via {e['formula_ref']}; src {e['source_name']})"
                )
            else:
                psg = e.get("passage") or ""
                if len(psg) > max_passage:
                    psg = psg[:max_passage] + "…"
                lines.append(
                    f"{tag}{tk} {e['source_name']} «{psg}» (ref {e['source_ref']})"
                )
        return "\n".join(lines)

    def to_citation_index(self) -> list[dict]:
        """Render entries as the memo's citation_index (the `[N]` footnote list).

        Maps onto the existing IntelligenceMemoRecord.citation_index shape so
        the UI and PDF appendix render evidence receipts with no new component.
        """
        out = []
        for e in self._entries:
            out.append({
                "n": e["n"],
                "kind": e["kind"],
                "source_type": e["source_name"],
                "source_id": e.get("source_ref"),
                "url": e.get("url"),
                "label": e.get("label"),
                "excerpt": e.get("passage"),
                "metric": e.get("metric"),
                "value": e.get("display_value"),
                "formula_ref": e.get("formula_ref"),
            })
        return out
