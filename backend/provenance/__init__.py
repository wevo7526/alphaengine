"""
Provenance layer (Build Plan Phase 1).

Every quantitative claim and every qualitative assertion in a memo binds to
a verifiable receipt:

  - a **computed receipt** for a number the engine produced, or
  - a **source receipt** for a passage retrieved from a filing / news / web.

The `FactSheet` is the only factual material the narration LLM is allowed to
use; the validator rejects any output carrying a fact it cannot trace back to
a FactSheet entry.

Public API:
    content_hash, computed_receipt, source_receipt   -- build receipts
    FactSheet                                         -- in-memory fact container
    EvidenceRepository                                -- persistence + content-hash cache
"""

from provenance.store import (
    content_hash,
    computed_receipt,
    source_receipt,
    FactSheet,
)
from provenance.repository import EvidenceRepository

__all__ = [
    "content_hash",
    "computed_receipt",
    "source_receipt",
    "FactSheet",
    "EvidenceRepository",
]
