"""nlp_audit — prove the NLP is doing real analytical work (Build Plan §2.4)."""

from scripts.nlp_audit.audit import (
    attribution_report,
    ablation_report,
    coverage_report,
)

__all__ = ["attribution_report", "ablation_report", "coverage_report"]
