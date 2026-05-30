"""
Golden-output tests for quant_core.pairs.

Seeded inputs (PCG64), frozen decision-relevant outputs. Freezes the numbers a
consumer acts on — hedge ratio, ADF p-value, half-life, z-score, stability, and
the cointegration verdict — so a dep bump that moves a regression tail fails CI.
"""

import numpy as np

from quant_core.pairs import compute_spread_signal, find_cointegrated_pairs


def _pair():
    rng = np.random.default_rng(2024)
    trend = np.cumsum(rng.normal(0, 0.01, 300))
    a = np.exp(3.0 + trend + 0.01 * rng.normal(0, 1, 300))
    b = np.exp(2.0 + 0.8 * trend + 0.01 * rng.normal(0, 1, 300))
    c = np.exp(1.5 + np.cumsum(rng.normal(0, 0.012, 300)))
    return a, b, c


def test_compute_spread_signal_golden():
    a, b, _ = _pair()
    s = compute_spread_signal(a.tolist(), b.tolist(), symbol_a="AAA", symbol_b="BBB")
    assert s["n_observations"] == 300
    assert s["hedge_ratio"] == 1.2564
    assert s["cointegration"]["p_value"] == 0.0
    assert s["cointegration"]["significant_at_5pct"] is True
    assert s["half_life_days"] == 0.78
    assert s["spread"]["current_zscore"] == -1.266
    assert s["stability"]["stability_score"] == 0.877
    # Half-life 0.78 < MIN_HALF_LIFE_DAYS (1.0) → fails the tradability gate
    # even though ADF rejects: the verdict is conjunctive, by design.
    assert s["cointegrated"] is False
    assert s["trade_signal"] == "hold"


def test_find_cointegrated_pairs_golden():
    a, b, c = _pair()
    out = find_cointegrated_pairs(
        {"AAA": a.tolist(), "BBB": b.tolist(), "CCC": c.tolist()},
        cointegrated_only=False,
    )
    assert out["n_evaluated"] == 3
    assert out["n_cointegrated"] == 0
    # Sorted by ADF p-value ascending.
    assert [(p["ticker_a"], p["ticker_b"]) for p in out["pairs"]] == [
        ("AAA", "BBB"), ("BBB", "CCC"), ("AAA", "CCC"),
    ]


def test_compute_spread_signal_too_few_obs():
    out = compute_spread_signal([1.0] * 50, [1.0] * 50, symbol_a="X", symbol_b="Y")
    assert out["cointegrated"] is False
    assert "Insufficient overlap" in out["error"]


def test_same_ticker_rejected():
    out = compute_spread_signal([1.0] * 200, [1.0] * 200, symbol_a="X", symbol_b="X")
    assert out["error"] == "Same ticker for both legs"
