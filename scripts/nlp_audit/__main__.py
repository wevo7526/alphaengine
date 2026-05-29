"""`python -m scripts.nlp_audit` → run the diagnostic demo.

With no memo to inspect this prints a self-contained attribution + ablation
example so the harness is runnable out of the box. Wire it to a real memo by
importing `attribution_report` / `ablation_report` / `coverage_report`.
"""

from scripts.nlp_audit.audit import _demo

if __name__ == "__main__":
    _demo()
