"""
Golden-output tests for quant_core.risk.compute_var_cvar.

Seeded return stream (PCG64), frozen VaR/CVaR layers. The bootstrap uses a
fixed internal seed (42) so the historical CI is reproducible.
"""

import numpy as np

from quant_core.risk import compute_var_cvar


def _returns():
    rng = np.random.default_rng(99)
    return (rng.normal(0.0005, 0.012, 500) - 0.0008 * (rng.random(500) > 0.95)).tolist()


def test_var_cvar_golden():
    r = compute_var_cvar(_returns(), confidence=0.95)
    assert r["n_obs"] == 500
    assert r["parametric"]["var_pct"] == 2.02
    assert r["cornish_fisher"]["var_pct"] == 1.95
    assert r["cornish_fisher"]["z_adjusted"] == 1.592
    assert r["historical"]["var_pct"] == 2.01
    # CI bounds ordered low <= high (loss magnitudes).
    assert r["historical"]["ci_95_low_pct"] == 1.77
    assert r["historical"]["ci_95_high_pct"] == 2.15
    assert r["cvar"]["cvar_pct"] == 2.57


def test_var_cvar_too_few_obs():
    out = compute_var_cvar([0.01] * 10)
    assert out == {"error": "need >= 20 observations", "n_obs": 10}


def test_var_cvar_is_pure():
    r = _returns()
    assert compute_var_cvar(r) == compute_var_cvar(r)
