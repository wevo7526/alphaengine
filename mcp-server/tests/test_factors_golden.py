"""
Golden-output tests for quant_core.factors.decompose_factors.

Seeded portfolio built from known factor loadings (β market 1.1, size 0.4,
value -0.2 + alpha); the regression should recover them. Frozen so a
statsmodels/numpy bump that shifts the HAC fit fails CI.
"""

import numpy as np

from quant_core.factors import decompose_factors


def _data():
    rng = np.random.default_rng(7)
    T = 250
    mkt = rng.normal(0.0004, 0.01, T)
    size = rng.normal(0.0, 0.006, T)
    val = rng.normal(0.0, 0.005, T)
    port = 0.0002 + 1.1 * mkt + 0.4 * size - 0.2 * val + rng.normal(0, 0.004, T)
    return port, {"market": mkt.tolist(), "size": size.tolist(), "value": val.tolist()}


def test_decompose_factors_golden():
    port, factors = _data()
    f = decompose_factors(port.tolist(), factors, risk_free_rate=0.04)
    assert f["n_observations"] == 250
    assert f["alpha"] == 2.1
    assert f["factor_betas"] == {"market": 1.0947, "size": 0.3835, "value": -0.198}
    assert f["r_squared"] == 0.887
    assert f["residual_vol"] == 5.9
    assert f["model"] == "3-factor"


def test_decompose_factors_too_few_obs():
    out = decompose_factors([0.01] * 10, {"market": [0.01] * 10})
    assert out == {"error": "Need 30+ observations"}


def test_decompose_factors_no_factors():
    out = decompose_factors([0.01] * 50, {})
    assert out == {"error": "No factor data"}
