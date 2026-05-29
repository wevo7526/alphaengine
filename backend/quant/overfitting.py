"""
Anti-overfitting layer (Build Plan §3.1) — the moat: tell the user when an
idea is probably noise.

Implements, from the published formulas:
  - Probabilistic Sharpe Ratio (PSR) and Deflated Sharpe Ratio (DSR)
    — Bailey & López de Prado (2014). DSR adjusts the Sharpe for the number
    of trials and for non-normal returns (skew/kurtosis).
  - Probability of Backtest Overfitting (PBO) via Combinatorially Symmetric
    Cross-Validation (CSCV) — Bailey, Borwein, López de Prado, Zhu (2017).
  - Purged + embargoed k-fold splits for overlapping-label financial data
    — López de Prado, "Advances in Financial Machine Learning" (2018).
  - HypothesisLedger — record EVERY idea/config tried per run, so the trial
    count (the denominator the stats above require) is real, not guessed.

Pure numpy/scipy. No look-ahead, no LLM. Fully deterministic given inputs.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats

_EULER = 0.5772156649015329


# ── Hypothesis ledger ───────────────────────────────────────────────────

@dataclass
class HypothesisLedger:
    """Records every idea/config evaluated in a run.

    The number of trials is the denominator for the Deflated Sharpe Ratio;
    silently reporting a backtest's Sharpe without it is how noise gets sold
    as alpha. `trials_sharpe_std` feeds DSR's expected-max-Sharpe term.
    """

    trials: list[dict] = field(default_factory=list)

    def record(self, config_id: str, sharpe: float | None, **meta) -> None:
        self.trials.append({"config_id": config_id, "sharpe": sharpe, **meta})

    @property
    def n_trials(self) -> int:
        return len(self.trials)

    def sharpes(self) -> list[float]:
        return [float(t["sharpe"]) for t in self.trials
                if t.get("sharpe") is not None and math.isfinite(float(t["sharpe"]))]

    def trials_sharpe_std(self) -> float:
        s = self.sharpes()
        return float(np.std(s, ddof=1)) if len(s) >= 2 else 0.0


# ── Sharpe statistics ───────────────────────────────────────────────────

def _per_period_sharpe(returns: np.ndarray) -> float:
    sd = returns.std(ddof=1)
    if sd == 0 or not math.isfinite(sd):
        return 0.0
    return float(returns.mean() / sd)


def probabilistic_sharpe_ratio(
    sharpe: float, n_obs: int, skew: float, kurtosis: float, sr_benchmark: float = 0.0,
) -> float:
    """PSR: P(true per-period Sharpe > sr_benchmark). Bailey & LdP (2014).

    `kurtosis` is Pearson (normal = 3). Returns a probability in [0, 1].
    """
    if n_obs < 2:
        return 0.0
    denom = 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe ** 2
    if denom <= 0:
        denom = 1e-9
    z = (sharpe - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return float(stats.norm.cdf(z))


def expected_max_sharpe(n_trials: int, trials_sharpe_std: float) -> float:
    """E[max Sharpe] over N independent trials of noise (per-period units).

    SR0 = σ_SR · [ (1-γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) ].
    This is the benchmark a *real* strategy must beat to be non-spurious.
    """
    if n_trials < 2 or trials_sharpe_std <= 0:
        return 0.0
    a = stats.norm.ppf(1.0 - 1.0 / n_trials)
    b = stats.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return float(trials_sharpe_std * ((1.0 - _EULER) * a + _EULER * b))


def deflated_sharpe_ratio(
    returns: list[float],
    *,
    n_trials: int,
    trials_sharpe_std: float | None = None,
) -> dict:
    """Deflated Sharpe Ratio for a return stream.

    DSR = PSR(SR0), where SR0 = expected max Sharpe across `n_trials`. A DSR
    near 1 means the result survives the multiple-testing correction; near
    0 means it's probably noise. Returns per-period and annualized Sharpe,
    PSR(0), SR0, and DSR. `trials_sharpe_std` should come from the ledger;
    when absent we estimate it from the result's own sampling error (a
    conservative lower bound on selection variance).
    """
    arr = np.asarray([float(r) for r in (returns or []) if r is not None], dtype=float)
    n = arr.size
    if n < 8:
        return {"error": "need >= 8 observations", "n_obs": int(n)}

    sr = _per_period_sharpe(arr)
    skew = float(stats.skew(arr, bias=False)) if n > 2 else 0.0
    kurt = float(stats.kurtosis(arr, fisher=False, bias=False)) if n > 3 else 3.0
    psr0 = probabilistic_sharpe_ratio(sr, n, skew, kurt, 0.0)

    # Sampling SD of the Sharpe estimator under the null (Lo, 2002) — used as a
    # floor for trial-Sharpe dispersion when the ledger doesn't supply one.
    sr_est_sd = math.sqrt((1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr ** 2) / (n - 1)) if n > 1 else 0.0
    std_for_max = trials_sharpe_std if (trials_sharpe_std and trials_sharpe_std > 0) else sr_est_sd
    sr0 = expected_max_sharpe(max(2, n_trials), std_for_max)
    dsr = probabilistic_sharpe_ratio(sr, n, skew, kurt, sr0)

    return {
        "n_obs": int(n),
        "n_trials": int(n_trials),
        "sharpe_per_period": round(sr, 4),
        "sharpe_annualized": round(sr * math.sqrt(252), 4),
        "skew": round(skew, 4),
        "kurtosis": round(kurt, 4),
        "psr_vs_zero": round(psr0, 4),
        "sr0_expected_max": round(sr0, 4),
        "deflated_sharpe": round(dsr, 4),
        "trials_sharpe_std": round(std_for_max, 4),
        # The headline the UI shows INSTEAD of raw Sharpe.
        "verdict": ("likely_noise" if dsr < 0.5 else "marginal" if dsr < 0.9 else "robust"),
    }


def bootstrap_sharpe_ci(
    returns: list[float], *, n_boot: int = 1000, conf: float = 0.95, seed: int = 7,
) -> dict:
    """Bootstrap confidence interval for the (per-period) Sharpe ratio."""
    arr = np.asarray([float(r) for r in (returns or []) if r is not None], dtype=float)
    if arr.size < 8:
        return {"error": "need >= 8 observations"}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_boot, arr.size))
    samples = arr[idx]
    means = samples.mean(axis=1)
    sds = samples.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        srs = np.where(sds > 0, means / sds, 0.0)
    lo = float(np.percentile(srs, (1 - conf) / 2 * 100))
    hi = float(np.percentile(srs, (1 + conf) / 2 * 100))
    return {
        "sharpe_per_period": round(_per_period_sharpe(arr), 4),
        "ci_low": round(lo, 4), "ci_high": round(hi, 4),
        "conf": conf, "n_boot": n_boot,
        "excludes_zero": bool(lo > 0 or hi < 0),
    }


# ── Purged + embargoed k-fold ───────────────────────────────────────────

def purged_kfold_indices(n_samples: int, n_splits: int = 5, embargo_pct: float = 0.01) -> list[dict]:
    """Purged + embargoed k-fold splits for overlapping-label data.

    Training observations whose information overlaps the test window are
    *purged*; an *embargo* of `embargo_pct·n` observations after each test
    fold is also dropped. Prevents the leakage that fakes good CV results.
    Returns [{"train": [...], "test": [...]}] of index lists.
    """
    if n_samples < n_splits or n_splits < 2:
        return []
    embargo = int(n_samples * embargo_pct)
    folds = np.array_split(np.arange(n_samples), n_splits)
    out = []
    for fold in folds:
        t0, t1 = int(fold[0]), int(fold[-1])
        test = list(range(t0, t1 + 1))
        # Purge the test window and embargo the tail that follows it.
        purge_lo, purge_hi = t0, min(n_samples - 1, t1 + embargo)
        train = [i for i in range(n_samples) if i < purge_lo or i > purge_hi]
        if train and test:
            out.append({"train": train, "test": test, "embargo": embargo})
    return out


# ── PBO via CSCV ────────────────────────────────────────────────────────

def _block_sharpe(sums: np.ndarray, sqs: np.ndarray, counts: np.ndarray, blocks: list[int]) -> np.ndarray:
    """Per-config Sharpe over the selected blocks from precomputed moments."""
    s = sums[blocks].sum(axis=0)
    q = sqs[blocks].sum(axis=0)
    c = counts[blocks].sum()
    mean = s / c
    var = q / c - mean ** 2
    sd = np.sqrt(np.maximum(var, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sd > 0, mean / sd, 0.0)


def pbo_cscv(pnl_matrix, n_splits: int = 10, max_combos: int = 2000) -> dict:
    """Probability of Backtest Overfitting via CSCV (Bailey et al. 2017).

    `pnl_matrix`: shape (T observations, N configurations) of per-period
    returns/PnL — one column per strategy variant from the hypothesis ledger.
    Splits T into `n_splits` contiguous blocks, enumerates all balanced
    in-sample/out-of-sample partitions, and for each picks the IS-best config
    and measures its OOS rank. PBO = fraction of partitions where the IS-best
    config lands below the OOS median (logit ≤ 0).
    """
    M = np.asarray(pnl_matrix, dtype=float)
    if M.ndim != 2 or M.shape[1] < 2 or M.shape[0] < n_splits * 2:
        return {"error": "need (T>=2S observations, N>=2 configs)", "shape": list(M.shape)}
    T, N = M.shape
    if n_splits % 2 != 0:
        n_splits -= 1  # CSCV needs an even number of blocks to halve

    blocks = np.array_split(np.arange(T), n_splits)
    # Precompute per-block moments per config.
    sums = np.vstack([M[b].sum(axis=0) for b in blocks])      # (S, N)
    sqs = np.vstack([(M[b] ** 2).sum(axis=0) for b in blocks])  # (S, N)
    counts = np.array([len(b) for b in blocks], dtype=float)   # (S,)

    block_ids = list(range(n_splits))
    half = n_splits // 2
    combos = list(itertools.combinations(block_ids, half))
    if len(combos) > max_combos:
        # Deterministic subsample to bound cost on large S.
        step = max(1, len(combos) // max_combos)
        combos = combos[::step][:max_combos]

    logits = []
    for is_blocks in combos:
        oos_blocks = [b for b in block_ids if b not in is_blocks]
        is_perf = _block_sharpe(sums, sqs, counts, list(is_blocks))
        oos_perf = _block_sharpe(sums, sqs, counts, oos_blocks)
        n_star = int(np.argmax(is_perf))
        # Rank of the IS-best config OOS (1 = worst .. N = best).
        order = np.argsort(np.argsort(oos_perf))  # ranks 0..N-1
        rank = order[n_star] + 1
        w = rank / (N + 1)
        w = min(max(w, 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1.0 - w)))

    logits_arr = np.asarray(logits)
    pbo = float(np.mean(logits_arr <= 0.0)) if logits_arr.size else float("nan")
    return {
        "pbo": round(pbo, 4),
        "n_partitions": int(logits_arr.size),
        "n_configs": int(N),
        "n_splits": int(n_splits),
        "logit_mean": round(float(np.mean(logits_arr)), 4) if logits_arr.size else None,
        "verdict": ("overfit" if pbo > 0.5 else "acceptable" if pbo > 0.2 else "robust"),
    }


def augment_backtest_overfitting(
    report: dict,
    returns: list[float],
    n_trials: int = 1,
    pnl_matrix=None,
) -> dict:
    """Attach the anti-overfitting verdict to a backtest report in place.

    Always replaces the naive Sharpe headline with the **deflated** Sharpe
    (Build Plan §3.7: "No backtest displays raw Sharpe"). PBO is computed only
    when a multi-config pnl matrix is supplied — a single-config backtest can't
    estimate it, and we say so rather than faking a number.
    """
    try:
        dsr = deflated_sharpe_ratio(list(returns or []), n_trials=max(1, int(n_trials)))
        report["deflated_sharpe"] = dsr
        report["overfitting_verdict"] = dsr.get("verdict")
        report["sharpe_display"] = {
            "headline": "deflated_sharpe",
            "value": dsr.get("deflated_sharpe"),
            "note": "Deflated Sharpe corrects the raw Sharpe for the number of "
                    "trials and non-normal returns; raw Sharpe is not shown as "
                    "a headline because it overstates skill under selection.",
        }
        report["bootstrap_sharpe_ci"] = bootstrap_sharpe_ci(list(returns or []))
    except Exception:
        report["deflated_sharpe"] = {"error": "could not compute"}
    if pnl_matrix is not None:
        try:
            report["pbo"] = pbo_cscv(pnl_matrix)
        except Exception:
            report["pbo"] = {"error": "could not compute"}
    else:
        report["pbo"] = {"note": "PBO requires multiple strategy configurations "
                                 "(a pnl matrix); not available for a single-config run."}
    return report
