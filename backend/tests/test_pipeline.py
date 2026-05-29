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


def test_finalize_converts_markers_and_continues_numbering():
    fs = build_fact_sheet(**_state())
    memo = {
        "analysis": "VIX is 25.78 [[ev:1]] in a late_cycle regime [[ev:2]]; long AAPL at 257.48 [[ev:3]], stop 240.0 [[ev:4]].",
        "executive_summary": "Conviction 72 [[ev:6]].",
        "key_findings": ["Take profit at 290.0 [[ev:5]]"],
        "citation_index": [{"n": 1, "source_type": "market_price", "source_id": "X"},
                           {"n": 2, "source_type": "fred_series", "source_id": "Y"}],
    }
    v = validate_against_fact_sheet(memo, fs)
    assert v.ok, (v.orphans, v.dangling)

    fin = finalize_with_evidence(memo, fs, base_index=2)
    out = fin["memo"]
    # ev:1 → [3], ev:3 → [5], ev:6 → [8]
    assert "[3]" in out["analysis"] and "[5]" in out["analysis"]
    assert "[8]" in out["executive_summary"]
    assert "[7]" in out["key_findings"][0]
    # evidence footnotes continue past the 2 existing source citations
    assert all(c["n"] > 2 for c in fin["citation_additions"])
    # every cited evidence carries a content_hash link to persist
    assert all(l["content_hash"] for l in fin["links"])


def test_computed_citation_label_carries_value_and_formula():
    fs = build_fact_sheet(**_state())
    memo = {"analysis": "VIX is 25.78 [[ev:1]].", "citation_index": []}
    fin = finalize_with_evidence(memo, fs, base_index=0)
    add = fin["citation_additions"][0]
    assert add["label"] == "VIX = 25.78"                 # value visible in the receipt
    assert "get_macro_snapshot" in add["source_id"]      # named formula visible
