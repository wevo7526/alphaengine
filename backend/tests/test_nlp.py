"""Phase 2 — NLP signal suite (Build Plan §2). No live network/API calls.

Covers: filing-change scoring (golden fixtures), section parsing, transcript
tone, the signal contract + aggregator, 8-K novelty, the Firecrawl-first
ingest (faked deps), and the nlp_audit ablation that proves NLP moves
conviction.
"""

import asyncio
from pathlib import Path

import pytest

from agents.nlp.filing_diff import filing_change_score, build_filing_signal
from agents.nlp.sections import extract_section_from_text, best_effort_sections
from agents.nlp.transcripts import score_transcript, build_call_tone_signal
from agents.nlp.signals import NLPSignal, aggregate_nlp_tilt, tilt_by_ticker
from agents.nlp.events_novelty import score_8k_novelty, build_event_novelty_signal
from agents.nlp.runner import apply_nlp_tilt_to_ideas

_FIX = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


# ── 2.1c filing-change scoring (golden fixtures) ────────────────────────

def test_filing_change_golden_large_bearish_change():
    prior = _fixture("filing_1A_prior.txt")
    current = _fixture("filing_1A_current.txt")
    # Parse the section out of each (as we would from a Firecrawl scrape).
    cur_sec = extract_section_from_text(current, "1A")
    pri_sec = extract_section_from_text(prior, "1A")
    assert cur_sec and pri_sec

    score = filing_change_score(cur_sec, pri_sec, section="1A")
    # The current filing adds material weakness + going concern language.
    assert score["change_score"] >= 0.18
    assert score["magnitude_bucket"] in ("moderate", "high", "severe")
    assert score["n_added"] >= 1
    # Some added sentence should mention the new material risk.
    joined = " ".join(score["added_excerpts"]).lower()
    assert "going concern" in joined or "material weakness" in joined

    sig, receipts = build_filing_signal("TEST", score, accession="acc-1", filing_url="http://x")
    assert sig.signal_name == "filing_change"
    assert sig.direction == "bearish"           # Lazy Prices: large change → bearish
    assert len(receipts) == len(sig.evidence_ids) >= 1


def test_filing_change_identical_is_low():
    text = _fixture("filing_1A_prior.txt")
    sec = extract_section_from_text(text, "1A")
    score = filing_change_score(sec, sec, section="1A")
    assert score["change_score"] < 0.05
    assert score["magnitude_bucket"] == "low"


def test_no_prior_yields_no_signal():
    cur = extract_section_from_text(_fixture("filing_1A_current.txt"), "1A")
    score = filing_change_score(cur, "", section="1A")
    assert score["has_prior"] is False
    sig, receipts = build_filing_signal("TEST", score)
    assert sig is None and receipts == []


# ── 2.1b section parser ─────────────────────────────────────────────────

def test_section_parser_skips_toc_and_stops_at_next_item():
    rf = extract_section_from_text(_fixture("filing_1A_current.txt"), "1A")
    assert "our business faces intense competition" in rf.lower()
    assert "unresolved staff comments" not in rf.lower()  # stopped at Item 1B


# ── 2.2 transcript tone ─────────────────────────────────────────────────

def test_transcript_tone_and_delta():
    upbeat = "Operator. " + "We delivered record revenue and raised guidance with strong demand. " * 12
    cagey = "Operator. " + "The macro is challenging and uncertain with headwinds and softness; results may be volatile. " * 12
    su, sc = score_transcript(upbeat), score_transcript(cagey)
    assert su["tone"] > sc["tone"]
    assert sc["uncertainty"] > su["uncertainty"]

    improving, _ = build_call_tone_signal("X", su, sc)   # prior cagey → now upbeat
    assert improving.direction == "bullish"
    deteriorating, _ = build_call_tone_signal("X", sc, su)
    assert deteriorating.direction == "bearish"


# ── 2.3 signal contract + aggregator ────────────────────────────────────

def test_aggregator_tilt_sign_and_bounds():
    sigs = [
        NLPSignal(ticker="A", signal_name="filing_change", value=0.8, direction="bearish", confidence=0.9),
        NLPSignal(ticker="A", signal_name="call_tone", value=0.2, direction="bullish", confidence=0.4),
    ]
    agg = aggregate_nlp_tilt(sigs)
    assert -1.0 <= agg["tilt"] <= 1.0 and agg["tilt"] < 0  # bearish filing dominates


def test_signal_value_and_confidence_clamped():
    s = NLPSignal(ticker="a", signal_name="news_sentiment", value=5, confidence=-1)
    assert s.value == 1.0 and s.confidence == 0.0 and s.ticker == "A"


# ── 2.1d 8-K novelty ────────────────────────────────────────────────────

def test_8k_novelty_flags_new_item_and_bearish_restatement():
    filings = [
        {"items": ["Item 4.02: Non-reliance"], "filedAt": "2025-03-01"},
        {"items": ["Item 2.02: Results"], "filedAt": "2025-01-15"},
        {"items": ["Item 2.02: Results"], "filedAt": "2024-10-15"},
    ]
    score = score_8k_novelty(filings)
    assert "4.02" in score["novel_items"]
    assert score["direction"] == "bearish"      # 4.02 restatement
    sig, receipts = build_event_novelty_signal("X", score, accession="acc")
    assert sig.signal_name == "event_novelty" and len(receipts) == 1


# ── Firecrawl-first ingest (faked deps, zero network) ───────────────────

def test_filing_ingest_uses_firecrawl_not_secapi(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "FILING_NLP_ENABLED", True, raising=False)
    from agents.nlp.filing_ingest import run_filing_change, SecBudget
    SecBudget.reset()

    cur = _fixture("filing_1A_current.txt")
    pri = _fixture("filing_1A_prior.txt")

    class FakeSec:
        async def aget_recent_filings(self, ticker, form, limit):
            return {"filings": [
                {"accessionNo": "a-cur", "linkToFilingDetails": "https://sec.gov/cur.htm", "filedAt": "2025-02-01", "formType": form},
                {"accessionNo": "a-pri", "linkToFilingDetails": "https://sec.gov/pri.htm", "filedAt": "2024-02-01", "formType": form},
            ]}
        def extract_risk_factors(self, url):
            raise AssertionError("sec-api extract must not be called on the Firecrawl path")

    class FakeFire:
        async def ascrape_full(self, url, max_chars=120000):
            return {"content": cur if "cur" in url else pri, "url": url}

    class FakeRepo:
        @staticmethod
        async def get_by_source_ref(sn, sr):
            return []

    r = asyncio.run(run_filing_change(
        "TEST", section="1A", form="10-K",
        sec_client=FakeSec(), firecrawl=FakeFire(), evidence_repo=FakeRepo(), use_llm=False,
    ))
    assert r["sources"] == {"latest": "firecrawl", "prior": "firecrawl"}
    assert SecBudget._used == 1                      # listing only
    assert r["signal"] and r["signal"].direction == "bearish"
    assert len(r["cache_receipts"]) == 2


def test_filing_ingest_budget_guard_blocks_when_exhausted(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "FILING_NLP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SEC_CALL_BUDGET", 0, raising=False)
    from agents.nlp.filing_ingest import run_filing_change, SecBudget
    SecBudget.reset()

    class FakeSec:
        async def aget_recent_filings(self, *a, **k):
            raise AssertionError("must not call sec-api when budget is 0")

    r = asyncio.run(run_filing_change("TEST", sec_client=FakeSec(), firecrawl=None, evidence_repo=None))
    assert r["signal"] is None and r["warnings"]


# ── 2.4 nlp_audit ablation: NLP must move conviction ────────────────────

def test_ablation_nlp_moves_conviction():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.nlp_audit.audit import ablation_report, attribution_report

    ideas = [{"ticker": "AAPL", "conviction": 70}, {"ticker": "MSFT", "conviction": 68}]
    signals = [
        NLPSignal(ticker="AAPL", signal_name="filing_change", value=0.7, direction="bearish", confidence=0.9),
    ]
    rep = ablation_report(ideas, tilt_by_ticker(signals))
    assert rep["nlp_moves_conviction"] is True
    assert rep["conviction_deltas"]["AAPL"] < 0          # bearish dropped AAPL
    # AAPL was top (70 vs 68); a bearish drop should flip the ranking.
    assert rep["rankings_changed"] is True

    # Attribution flags a signal that contributes nothing as theater.
    neutral = [NLPSignal(ticker="X", signal_name="news_sentiment", value=0.5, direction="neutral", confidence=0.5)]
    att = attribution_report(neutral)
    assert "news_sentiment" in att["theater_signals"]


def test_tilt_off_is_noop():
    ideas = [{"ticker": "AAPL", "conviction": 70}]
    out, adj = apply_nlp_tilt_to_ideas([dict(i) for i in ideas], {})
    assert out[0]["conviction"] == 70 and adj == []
