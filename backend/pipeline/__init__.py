"""
Three-stage memo pipeline (Build Plan Phase 1):

    compute  → run all deterministic math + retrieval, emit a Fact Sheet
    narrate  → LLM writes the memo using ONLY Fact Sheet entries, citing [[ev:n]]
    validate → linter rejects any output with an untraceable fact (hard gate)

"Compute first. Narrate second. Validate third. The LLM never originates a
number." The validator is the enforcement of that principle.
"""

from pipeline.compute import build_fact_sheet
from pipeline.narrate import (
    fact_sheet_prompt_block,
    repair_prompt_block,
    validate_against_fact_sheet,
    finalize_with_evidence,
)
from pipeline.validate import (
    validate_memo,
    ValidationResult,
    extract_citation_markers,
    extract_numeric_tokens,
)

__all__ = [
    "build_fact_sheet",
    "fact_sheet_prompt_block",
    "repair_prompt_block",
    "validate_against_fact_sheet",
    "finalize_with_evidence",
    "validate_memo",
    "ValidationResult",
    "extract_citation_markers",
    "extract_numeric_tokens",
]
