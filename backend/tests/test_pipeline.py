"""Phase 1 — compute (Fact Sheet harvest) and narrate (footnote finalize)."""

from pipeline import build_fact_sheet, validate_against_fact_sheet, finalize_with_evidence


def _state():
    return dict(
        macro_context={"vix": 25.78, "current_regime": "late_cycle"},
        live_prices={"AAPL": 257.48},
        strategy_data={"trade_ideas": [
            {"ticker": "AAPL", "direction": "long", "conviction": 72,
             "stop_loss": 240.0, "take_profit": 290.0},
        ]},
        lineage={"sources": [
            {"type": "sec_filing", "id": "0000320193-25-000077", "tool": "get_recent_filings"},
        ]},
    )


def test_compute_harvests_trade_idea_and_macro_receipts():
    fs = build_fact_sheet(**_state())
    # VIX, regime, AAPL price, stop, take_profit, conviction, sec source
    assert len(fs) == 7
    rendered = fs.render_for_llm()
    assert "VIX = 25.78" in rendered
    assert "data.market.get_fundamentals" in rendered  # price has a named formula
    assert "agents.portfolio_strategist.trade_idea" in rendered  # trade-idea fields receipted


def test_finalize_is_deterministic_and_always_populates_citations():
    """Citations must appear even when the LLM emits NO [[ev:n]] markers."""
    fs = build_fact_sheet(**_state())
    memo = {
        "analysis": "VIX is 25.78 in a late_cycle regime; long AAPL at 257.48, stop 240.0.",
        "executive_summary": "We are long AAPL.",
        "trade_ideas": [{"ticker": "AAPL", "conviction": 72}],
        "risk_factors": [{"description": "macro risk"}],
    }
    fin = finalize_with_evidence(memo, fs)
    # citation_index = the FULL fact sheet, independent of LLM markers.
    assert len(fin["citation_index"]) == len(fs)
    # The trade idea gets its AAPL-ticker receipts attached (price/stop/etc.).
    idea_cites = fin["memo"]["trade_ideas"][0]["citations"]
    assert len(idea_cites) >= 1
    # The risk factor gets at least one anchor (DoD: every RF cited).
    assert len(fin["memo"]["risk_factors"][0]["citations"]) >= 1


def test_finalize_converts_markers_to_footnotes_when_present():
    fs = build_fact_sheet(**_state())
    memo = {
        "analysis": "VIX is 25.78 [[ev:1]] in a late_cycle regime [[ev:2]]; stop 240.0 [[ev:4]].",
        "key_findings": ["Take profit at 290.0 [[ev:5]]"],
        "trade_ideas": [], "risk_factors": [],
    }
    v = validate_against_fact_sheet(memo, fs)
    assert v.ok, (v.orphans, v.dangling)
    fin = finalize_with_evidence(memo, fs)
    out = fin["memo"]
    # n maps 1:1 to the Fact Sheet index (no base offset).
    assert "[1]" in out["analysis"] and "[2]" in out["analysis"] and "[4]" in out["analysis"]
    assert "[5]" in out["key_findings"][0]
    assert "[[ev:" not in out["analysis"]  # all markers converted


def test_computed_citation_label_carries_value_and_formula():
    fs = build_fact_sheet(**_state())
    fin = finalize_with_evidence({"analysis": "", "trade_ideas": [], "risk_factors": []}, fs)
    vix = next(c for c in fin["citation_index"] if c["label"].startswith("VIX"))
    assert vix["label"] == "VIX = 25.78"                  # value visible in the receipt
    assert "get_macro_snapshot" in vix["source_id"]       # named formula visible
