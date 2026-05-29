"""
NLP diagnostic harness (Build Plan §2.4) — prove NLP signals do real work.

Three views:
  - attribution_report: each NLP signal, its passages, and its numeric
    contribution to the conviction tilt. A signal that contributes 0
    everywhere is flagged as theater.
  - ablation_report: conviction rankings with NLP signals ON vs zeroed-OUT.
    A diff of "no change" means the NLP isn't actually wired into conviction.
  - coverage_report: % of memo names that received a fresh NLP pass.

Pure functions over the typed signals / trade ideas — no network, no DB.
Importable by tests and runnable as `python -m scripts.nlp_audit`.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script: make backend importable.
_BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def attribution_report(signals: list) -> dict:
    """Per-signal attribution + theater flags.

    `signals` is a list of NLPSignal (or dicts coerced to them). Returns the
    aggregate tilt, each signal's contribution, and the names of signals that
    contribute nothing anywhere (candidates for removal).
    """
    from agents.nlp.signals import NLPSignal, aggregate_nlp_tilt

    sigs = [s if isinstance(s, NLPSignal) else NLPSignal(**s) for s in signals]
    agg = aggregate_nlp_tilt(sigs)

    by_name_contrib: dict[str, float] = {}
    for c in agg["contributions"]:
        by_name_contrib[c["signal_name"]] = by_name_contrib.get(c["signal_name"], 0.0) + abs(c["contribution"])

    rows = []
    for s, c in zip(sigs, agg["contributions"]):
        rows.append({
            "signal_name": s.signal_name,
            "ticker": s.ticker,
            "direction": s.direction,
            "value": round(s.value, 4),
            "confidence": round(s.confidence, 4),
            "contribution": c["contribution"],
            "n_evidence": len(s.evidence_ids),
            "model": s.model,
        })

    theater = sorted([name for name, total in by_name_contrib.items() if total == 0.0])
    return {
        "tilt": agg["tilt"],
        "n_signals": len(sigs),
        "signals": rows,
        "contribution_by_name": {k: round(v, 6) for k, v in by_name_contrib.items()},
        "theater_signals": theater,  # contribute 0 everywhere
    }


def _ranking(ideas: list[dict]) -> list[str]:
    """Tickers ordered by conviction desc (ties broken by ticker)."""
    return [
        i["ticker"]
        for i in sorted(
            [x for x in ideas if isinstance(x, dict) and x.get("ticker")],
            key=lambda x: (-(float(x.get("conviction") or 0)), x.get("ticker", "")),
        )
    ]


def ablation_report(trade_ideas: list[dict], by_ticker_tilt: dict) -> dict:
    """Conviction with NLP tilt applied (ON) vs not applied (OFF).

    Returns the two rankings, whether the order changed, and per-idea deltas.
    `rankings_changed=False` AND all deltas zero ⇒ NLP isn't moving conviction.
    """
    from agents.nlp.runner import apply_nlp_tilt_to_ideas
    import copy

    off = copy.deepcopy(trade_ideas)
    on = copy.deepcopy(trade_ideas)
    on, adjustments = apply_nlp_tilt_to_ideas(on, by_ticker_tilt)

    rank_off = _ranking(off)
    rank_on = _ranking(on)
    conv_off = {i["ticker"]: float(i.get("conviction") or 0) for i in off if i.get("ticker")}
    conv_on = {i["ticker"]: float(i.get("conviction") or 0) for i in on if i.get("ticker")}
    deltas = {tk: round(conv_on.get(tk, 0) - conv_off.get(tk, 0), 2) for tk in conv_off}
    any_delta = any(abs(d) > 0 for d in deltas.values())

    return {
        "ranking_off": rank_off,
        "ranking_on": rank_on,
        "rankings_changed": rank_off != rank_on,
        "conviction_deltas": deltas,
        "any_conviction_change": any_delta,
        "adjustments": adjustments,
        # The headline assertion: NLP is genuinely wired in.
        "nlp_moves_conviction": any_delta,
    }


def coverage_report(bundle_or_memo: dict) -> dict:
    """Normalize the NLP coverage block from a runner bundle or a memo.

    Accepts either the runner bundle (`{"coverage": {...}}`) or a memo dict
    (`{"coverage": {"nlp": {...}}}`). Returns the coverage dict + a low-coverage
    flag the memo can use to downgrade confidence (Build Plan §3.6 backlog).
    """
    cov = {}
    if isinstance(bundle_or_memo, dict):
        c = bundle_or_memo.get("coverage") or {}
        cov = c.get("nlp") or c  # memo nests under coverage.nlp; bundle is flat
    covered_pct = float(cov.get("covered_pct", 0.0) or 0.0)
    return {
        **cov,
        "low_coverage": covered_pct < 50.0,
    }


def _demo() -> None:
    """Self-contained demo so `python -m scripts.nlp_audit` does something useful."""
    from agents.nlp.signals import NLPSignal

    signals = [
        NLPSignal(ticker="AAPL", signal_name="filing_change", value=0.6,
                  direction="bearish", confidence=0.9, evidence_ids=["h1", "h2"]),
        NLPSignal(ticker="AAPL", signal_name="call_tone", value=0.3,
                  direction="bullish", confidence=0.5, evidence_ids=["h3"]),
        NLPSignal(ticker="MSFT", signal_name="event_novelty", value=0.5,
                  direction="neutral", confidence=0.4, evidence_ids=["h4"]),
    ]
    from agents.nlp.signals import tilt_by_ticker
    ideas = [{"ticker": "AAPL", "conviction": 72}, {"ticker": "MSFT", "conviction": 60}]

    import json
    print("=== ATTRIBUTION ===")
    print(json.dumps(attribution_report(signals), indent=2))
    print("\n=== ABLATION ===")
    print(json.dumps(ablation_report(ideas, tilt_by_ticker(signals)), indent=2))


if __name__ == "__main__":
    _demo()
