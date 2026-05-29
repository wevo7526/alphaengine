"""Phase 3 — Quant Rigor suite (Build Plan §3). Pure math, no network/LLM."""

import numpy as np
import pytest

from quant.overfitting import (
    HypothesisLedger, deflated_sharpe_ratio, probabilistic_sharpe_ratio,
    expected_max_sharpe, bootstrap_sharpe_ci, purged_kfold_indices, pbo_cscv,
)
from quant.portfolio import hrp_weights, ideas_to_views, construct_portfolio
from quant.track_record import chain, verify_chain, head_hash, assert_point_in_time, LookaheadError
from quant.conviction import compose_conviction, brier_score, reliability_curve, calibration_report, suggest_reweight
from quant.regime_factors import regime_factor_tilts, regime_fit_score


# ── 3.1 anti-overfitting ────────────────────────────────────────────────

def test_more_trials_lowers_deflated_sharpe():
    rng = np.random.default_rng(0)
    r = list(rng.normal(0.001, 0.01, 252))
    d1 = deflated_sharpe_ratio(r, n_trials=1, trials_sharpe_std=0.08)
    dN = deflated_sharpe_ratio(r, n_trials=1000, trials_sharpe_std=0.08)
    assert d1["deflated_sharpe"] >= dN["deflated_sharpe"]
    assert dN["sr0_expected_max"] > d1["sr0_expected_max"]
    assert d1["verdict"] in ("likely_noise", "marginal", "robust")


def test_pure_noise_is_flagged():
    rng = np.random.default_rng(1)
    noise = list(rng.normal(0, 0.01, 252))
    d = deflated_sharpe_ratio(noise, n_trials=200, trials_sharpe_std=0.1)
    assert d["deflated_sharpe"] < 0.9


def test_psr_monotonic_in_sharpe():
    lo = probabilistic_sharpe_ratio(0.05, 252, 0.0, 3.0, 0.0)
    hi = probabilistic_sharpe_ratio(0.20, 252, 0.0, 3.0, 0.0)
    assert hi > lo


def test_pbo_distinguishes_noise_from_signal():
    rng = np.random.default_rng(2)
    noise = rng.normal(0, 1, (300, 20))
    good = rng.normal(0, 1, (300, 20)); good[:, 0] += 0.5
    p_noise = pbo_cscv(noise, n_splits=10)
    p_good = pbo_cscv(good, n_splits=10)
    assert p_good["pbo"] < p_noise["pbo"]
    assert p_good["verdict"] == "robust"


def test_purged_kfold_no_train_test_overlap():
    folds = purged_kfold_indices(100, n_splits=5, embargo_pct=0.02)
    assert len(folds) == 5
    for f in folds:
        assert not (set(f["train"]) & set(f["test"]))


def test_hypothesis_ledger_records_trials():
    L = HypothesisLedger()
    for i in range(10):
        L.record(f"c{i}", sharpe=0.1 * i)
    assert L.n_trials == 10 and L.trials_sharpe_std() > 0


# ── 3.2 portfolio (HRP) ─────────────────────────────────────────────────

def _toy_cov():
    rng = np.random.default_rng(3)
    base = rng.normal(0, 0.01, (300, 4))
    base[:, 1] += 0.7 * base[:, 0]  # B correlated with A
    cov = np.cov(base, rowvar=False)
    return {"matrix": cov.tolist(), "tickers": ["A", "B", "C", "D"]}


def test_hrp_weights_sum_to_one_and_nonneg():
    cov = _toy_cov()
    w = hrp_weights(cov["matrix"], cov["tickers"])["weights"]
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert all(v >= 0 for v in w.values())


def test_ideas_to_views_signs_and_confidence():
    views, conf = ideas_to_views([
        {"ticker": "AAPL", "direction": "bullish", "conviction": 80, "entry_zone": 100, "take_profit": 120},
        {"ticker": "XOM", "direction": "bearish", "conviction": 60},
    ])
    assert views["AAPL"] > 0 and views["XOM"] < 0 and conf["AAPL"] == 0.8


def test_construct_portfolio_has_traceable_receipts():
    cov = _toy_cov()
    ideas = [{"ticker": "A", "direction": "bullish", "conviction": 70}]
    cp = construct_portfolio(ideas, cov, method="hrp")
    assert abs(sum(cp["weights"].values()) - 1.0) < 1e-6
    assert cp["view_weight_receipts"] and all(r.get("content_hash") for r in cp["view_weight_receipts"])


# ── 3.3 honest simulator (tamper-evidence + look-ahead) ─────────────────

def _recs():
    return [
        {"ticker": "AAPL", "direction": "bullish", "conviction": 70, "signal_date": "2026-01-02", "entry_price": 100, "return_5d": 2.1},
        {"ticker": "MSFT", "direction": "bearish", "conviction": 60, "signal_date": "2026-01-03", "entry_price": 400, "return_5d": -1.0},
    ]


def test_chain_verifies_clean():
    recs = _recs()
    v = verify_chain(chain(recs), expected_head=head_hash(recs))
    assert v["ok"] and v["broken_at"] is None


def test_tampering_breaks_chain():
    recs = _recs()
    anchor = head_hash(recs)
    ch = chain(recs)
    ch[1]["return_5d"] = 99.9
    v = verify_chain(ch, expected_head=anchor)
    assert not v["ok"] and v["broken_at"] == 1


def test_lookahead_guard_raises_on_pre_signal_data():
    assert_point_in_time("2026-01-02", ["2026-01-03"])  # ok
    with pytest.raises(LookaheadError):
        assert_point_in_time("2026-01-02", ["2025-12-31"])


# ── 3.4 conviction calibration ──────────────────────────────────────────

def test_conviction_composite_aligned_vs_conflicting():
    strong = compose_conviction({"factor": 0.7, "filing_change": 0.6, "call_tone": 0.5})
    mixed = compose_conviction({"factor": 0.6, "filing_change": -0.6})
    assert strong["direction"] == "bullish" and strong["conviction"] > mixed["conviction"]
    assert any(r.get("content_hash") for r in strong["receipts"])  # decomposable receipts


def test_brier_extremes():
    assert brier_score([1, 1, 0, 0], [1, 1, 0, 0]) == 0.0
    assert brier_score([1, 1], [0, 0]) == 1.0


def test_reliability_curve_bins():
    probs = [0.05, 0.15, 0.85, 0.95]
    outs = [0, 0, 1, 1]
    curve = reliability_curve(probs, outs, n_bins=10)
    assert len(curve) == 10
    assert sum(b["n"] for b in curve) == 4


def test_reweight_favors_higher_edge():
    w = suggest_reweight({"filing_change": 0.62, "call_tone": 0.48})
    assert w["filing_change"] > w["call_tone"]


# ── 3.5 regime-conditional factor tilting ───────────────────────────────

def test_regime_tilts_differ_by_regime():
    off = regime_factor_tilts({"risk_off": 1.0})["weights"]
    on = regime_factor_tilts({"risk_on": 1.0})["weights"]
    assert off["low_vol"] > on["low_vol"]
    assert on["momentum"] > off["momentum"]
    assert abs(sum(off.values()) - 1.0) < 1e-6


def test_regime_fit_sign():
    assert regime_fit_score(["momentum"], {"risk_on": 1.0}) > 0
    assert regime_fit_score(["momentum"], {"risk_off": 1.0}) < 0
    assert regime_fit_score([], {"risk_on": 1.0}) == 0.0
