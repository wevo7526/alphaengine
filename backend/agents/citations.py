"""
agents/citations.py — Citation as a first-class type.

Every TradeIdea and RiskFactor carries a `citations` list. Inline markers
in memo prose resolve through the same shape. A Citation is a pointer to
exactly one entry in the memo's lineage block — the resolver in
infra/citations_resolver.py is responsible for filling in `url`, `label`,
and (later) `excerpt` from the matched lineage source.

Why a separate type rather than reusing the lineage dict shape:
  - Citations are claim-anchored (one numerical statement → one source).
    Lineage entries are tool-call-anchored (one tool invocation → one
    source). Many citations can reference the same lineage entry.
  - Citations need stable numeric ordering for inline footnotes (`[1]`).
    Lineage sources are grouped by type for the bulk panel; numbering
    them globally would be misleading.

The model is intentionally minimal — adding fields here forces a schema
change to every TradeIdea/RiskFactor consumer, so we keep it tight and
let the lineage layer carry the heavyweight metadata.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Canonical source_type taxonomy — mirrors infra/lineage.TOOL_SOURCE_TYPE.
# When an agent emits a citation with an unknown source_type, the resolver
# coerces it to "other" rather than rejecting the citation.
VALID_SOURCE_TYPES = frozenset({
    "sec_filing", "sec_insider", "sec_13f",
    "fred_series",
    "market_price",
    "news_article",
    "web_search",
    "technical",
    "screen",
    "computed",
    "other",
})


class Citation(BaseModel):
    """A claim-anchored pointer to one lineage source.

    `source_type` + `source_id` together form the resolution key — the
    resolver looks them up in `memo.lineage.sources` and fills in `url`,
    `label`, `excerpt` from the matched entry. Citations with no matching
    lineage entry are dropped before persist (LLM hallucination guard).
    """

    model_config = ConfigDict(extra="ignore")

    source_type: str = "other"
    source_id: str = ""
    # Filled by the resolver after lineage match. None means "tried but
    # the lineage entry had no URL" — the citation is still kept.
    url: Optional[str] = None
    label: Optional[str] = None
    # Optional supporting text (200-char snippet). Reserved for the
    # Firecrawl excerpt phase — not populated today, but the field is
    # here so the frontend can render it the moment it's available.
    excerpt: Optional[str] = None
    # Numeric index assigned by the resolver after dedup. Drives inline
    # `[N]` footnote rendering in memo prose. 0 means "unindexed".
    n: int = 0

    @field_validator("source_type", mode="before")
    @classmethod
    def coerce_source_type(cls, v):
        if not isinstance(v, str):
            return "other"
        v_low = v.strip().lower()
        return v_low if v_low in VALID_SOURCE_TYPES else "other"

    @field_validator("source_id", mode="before")
    @classmethod
    def coerce_source_id(cls, v):
        if v is None:
            return ""
        return str(v).strip()[:200]
