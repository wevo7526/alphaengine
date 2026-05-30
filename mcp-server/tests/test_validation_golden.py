"""
Golden-output tests for quant_core.validation.

Freezes deflated_sharpe / pbo_cscv outputs against fixed, seeded inputs. The
inputs come from numpy's PCG64 default_rng with a fixed seed (stable across
numpy releases), so the only thing that can move an output is a change in the
math or in a pinned numeric dependency. CI fails on drift — that is the whole
point: a minor scipy/numpy bump can shift a regression tail and therefore a
signal, and we want to know before it ships.

Re-freeze deliberately (never to "make the test pass"): if a dep bump is
intentional, regenerate the expected dicts and bump quant_core ENGINE_VERSION.
"""

import numpy as np

from quant_core.validation import deflated_sharpe, pbo_cscv


def _returns():
    # 300 daily returns, mildly positive drift — a realistic "is this noise?" case.
    return np.random.default_rng(42).normal(0.0008, 0.018, 300).tolist()


def _pnl_matrix():
    # 120 obs x 8 strategy configs of pure noise — PBO should be non-trivial.
    return np.random.default_rng(7).normal(0.0, 1.0, size=(120, 8))


GOLDEN_DEFLATED_SHARPE = {
    "n_obs": 300,
    "n_trials": 50,
    "sharpe_per_period": 0.0036,
    "sharpe_annualized": 0.0574,
    "skew": 0.2933,
    "kurtosis": 3.2505,
    "psr_vs_zero": 0.525,
    "sr0_expected_max": 0.1316,
    "deflated_sharpe": 0.0134,
    "trials_sharpe_std": 0.0578,
    "verdict": "likely_noise",
}

GOLDEN_PBO_CSCV = {
    "pbo": 0.373,
    "n_partitions": 252,
    "n_configs": 8,
    "n_splits": 10,
    "logit_mean": 0.3963,
    "verdict": "acceptable",
}


def test_deflated_sharpe_golden():
    assert deflated_sharpe(_returns(), n_trials=50) == GOLDEN_DEFLATED_SHARPE


def test_pbo_cscv_golden():
    assert pbo_cscv(_pnl_matrix()) == GOLDEN_PBO_CSCV


def test_deflated_sharpe_too_few_obs():
    # Contract: below 8 observations we say so rather than fake a number.
    out = deflated_sharpe([0.01, -0.02, 0.03], n_trials=10)
    assert out == {"error": "need >= 8 observations", "n_obs": 3}


def test_pbo_cscv_too_small():
    out = pbo_cscv(np.zeros((4, 1)))
    assert out.get("error")


def test_deflated_sharpe_is_pure():
    # Same input twice → identical output (no hidden state / RNG leak).
    r = _returns()
    assert deflated_sharpe(r, n_trials=50) == deflated_sharpe(r, n_trials=50)
