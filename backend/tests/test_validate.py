"""Phase 1 — the citation linter / hallucination regression guard.

Build Plan Verification: "inject a fabricated figure into the narration
stage; assert the validator rejects the memo." These tests assert exactly
that, plus the dangling-citation and mismatch behaviors.
"""

from provenance import FactSheet, computed_receipt
from pipeline import validate_memo


def _sheet():
    fs = FactSheet()
    fs.add(computed_receipt("AAPL P/E", 32.59, formula_ref="data.yahoo.fundamentals",
                            ticker="AAPL", source_name="yahoo"))            # ev:1
    fs.add(computed_receipt("AAPL VaR 95", 4.2, formula_ref="quant.risk.parametric_var",
                            ticker="AAPL"))                                  # ev:2
    return fs


def test_well_cited_memo_passes():
    fs = _sheet()
    prose = "Apple trades at a P/E of 32.59 [[ev:1]]. One-day VaR is 4.2% [[ev:2]]."
    r = validate_memo(prose, fs)
    assert r.ok
    assert r.orphans == [] and r.dangling == []


def test_injected_hallucination_is_rejected():
    """The core regression: a fabricated, uncited figure must hard-fail."""
    fs = _sheet()
    prose = "Apple trades at a P/E of 32.59 [[ev:1]]. We expect 47% upside this quarter."
    r = validate_memo(prose, fs)
    assert not r.ok
    assert "47" in r.orphans


def test_dangling_citation_is_rejected():
    fs = _sheet()
    prose = "Apple VaR is 4.2% [[ev:9]]."
    r = validate_memo(prose, fs)
    assert not r.ok
    assert 9 in r.dangling


def test_cited_but_wrong_value_is_a_warning_not_a_failure():
    fs = _sheet()
    prose = "Apple trades at a P/E of 18.0 [[ev:1]]."
    r = validate_memo(prose, fs)
    assert r.ok  # mismatch is a warning, not a hard fail
    assert "18.0" in r.mismatches


def test_generic_small_integers_are_not_claims():
    fs = _sheet()
    # "3 trade ideas" / "top 5" — generic counters, not citable claims.
    prose = "We surface 3 trade ideas across 2 sectors."
    r = validate_memo(prose, fs)
    assert r.ok and r.orphans == []
