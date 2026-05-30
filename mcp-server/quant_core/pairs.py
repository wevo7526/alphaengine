"""
Signals — pair-trade analytics over supplied price series.

Lifted (math-identical) from backend/quant/pairs.py, with the data-fetch removed:
the caller supplies aligned price arrays; nothing is fetched. The four
primitives a PM checks before sizing a pair — TLS hedge ratio, Engle-Granger
cointegration (ADF), Ornstein-Uhlenbeck half-life, rolling-correlation
stability — and a discrete trade signal.

Public (beta cut):
  compute_spread_signal(a_closes, b_closes, ...) -> dict   # one pair, end to end
  find_cointegrated_pairs(prices, ...) -> dict             # screen many series

Pure numpy/scipy/statsmodels. Deterministic given inputs on the pinned stack.
"""

from __future__ import annotations

import itertools
import math
from typing import Any

import numpy as np

from statsmodels.tsa.stattools import adfuller

# Pair-trading thresholds (documented so a caller can audit / override).
MIN_OBSERVATIONS = 126
COINTEGRATION_P_THRESHOLD = 0.05
MIN_HALF_LIFE_DAYS = 1.0
MAX_HALF_LIFE_DAYS = 60.0
MIN_STABILITY = 0.5
ZSCORE_WINDOW = 60
STABILITY_WINDOW = 60
ENTRY_ZSCORE = 2.0


def _clean(val: Any) -> Any:
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def _tls_hedge_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """Total Least Squares slope of `a ~ β·b` via SVD of the centered design.

    OLS biases β toward zero when b has noise (attenuation); TLS is the
    unbiased estimator when both legs have measurement noise (always true for
    two market prices).
    """
    if len(a) != len(b) or len(a) < 2:
        return float("nan")
    a_c = a - float(np.mean(a))
    b_c = b - float(np.mean(b))
    if np.std(b_c) < 1e-12:
        return float("nan")
    M = np.column_stack([b_c, a_c])
    try:
        _, _, Vt = np.linalg.svd(M, full_matrices=False)
    except np.linalg.LinAlgError:
        return float("nan")
    v = Vt[-1]
    if abs(v[1]) < 1e-12:
        return float("nan")
    return float(-v[0] / v[1])


def _ou_half_life(spread: np.ndarray) -> float | None:
    """Mean-reversion half-life via AR(1) on the differenced spread.

    Δs_t = a + b·s_{t-1} + ε_t ; half_life = -ln(2)/b. None when b≥0.
    """
    spread = np.asarray(spread, dtype=float)
    spread = spread[np.isfinite(spread)]
    n = len(spread)
    if n < 30:
        return None
    s_lag = spread[:-1]
    s_diff = np.diff(spread)
    X = np.column_stack([np.ones(len(s_lag)), s_lag])
    try:
        coefs, *_ = np.linalg.lstsq(X, s_diff, rcond=None)
    except np.linalg.LinAlgError:
        return None
    b = float(coefs[1])
    if b >= 0 or not math.isfinite(b):
        return None
    half_life = -math.log(2.0) / b
    if not math.isfinite(half_life) or half_life <= 0:
        return None
    return half_life


def _rolling_correlation_stability(
    a_returns: np.ndarray, b_returns: np.ndarray, window: int = STABILITY_WINDOW
) -> dict:
    """Stability = 1 - std(rolling correlation). High = structurally consistent."""
    n = min(len(a_returns), len(b_returns))
    if n < window + 5:
        return {"stability": None, "mean_corr": None, "std_corr": None, "n_windows": 0}

    rolling: list[float] = []
    for i in range(window, n):
        chunk_a = a_returns[i - window:i]
        chunk_b = b_returns[i - window:i]
        if np.std(chunk_a) > 0 and np.std(chunk_b) > 0:
            c = float(np.corrcoef(chunk_a, chunk_b)[0, 1])
            if math.isfinite(c):
                rolling.append(c)

    if len(rolling) < 5:
        return {"stability": None, "mean_corr": None, "std_corr": None, "n_windows": 0}

    arr = np.array(rolling)
    mean_c = float(np.mean(arr))
    std_c = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    stability = max(0.0, min(1.0, 1.0 - std_c))
    return {"stability": stability, "mean_corr": mean_c, "std_corr": std_c, "n_windows": len(rolling)}


def compute_spread(a_closes: np.ndarray, b_closes: np.ndarray, hedge_ratio: float) -> np.ndarray:
    """Log-price spread: s_t = log(P_a) - β·log(P_b)."""
    a = np.asarray(a_closes, dtype=float)
    b = np.asarray(b_closes, dtype=float)
    return np.log(a) - hedge_ratio * np.log(b)


def engle_granger_test(spread: np.ndarray) -> dict:
    """ADF on the spread. Null: unit root (NOT cointegrated). Reject at p<0.05."""
    spread_clean = np.asarray(spread, dtype=float)
    spread_clean = spread_clean[np.isfinite(spread_clean)]
    if len(spread_clean) < 30:
        return {"p_value": None, "test_statistic": None, "method": "engle_granger", "error": "insufficient_data"}
    try:
        result = adfuller(spread_clean, regression="c", autolag="AIC")
        return {
            "p_value": float(result[1]),
            "test_statistic": float(result[0]),
            "critical_values": {k: float(v) for k, v in result[4].items()},
            "n_lags": int(result[2]),
            "method": "engle_granger",
        }
    except Exception as e:  # noqa: BLE001
        return {"p_value": None, "test_statistic": None, "method": "engle_granger", "error": str(e)}


def compute_spread_signal(
    a_closes: list[float],
    b_closes: list[float],
    *,
    symbol_a: str = "A",
    symbol_b: str = "B",
    zscore_window: int = ZSCORE_WINDOW,
    stability_window: int = STABILITY_WINDOW,
) -> dict:
    """End-to-end pair analysis over two supplied, index-aligned close series.

    Identical math to backend analyze_pair, minus the fetch: hedge ratio (TLS),
    cointegration p-value (Engle-Granger ADF), spread z-score, OU half-life,
    rolling-correlation stability, and a discrete trade signal. A pair is
    `cointegrated=True` only when ADF, half-life, and stability all pass.
    """
    a_list = [float(x) for x in (a_closes or []) if x is not None]
    b_list = [float(x) for x in (b_closes or []) if x is not None]
    n = min(len(a_list), len(b_list))
    # Align to common length from the most recent end.
    a_list, b_list = a_list[-n:], b_list[-n:]

    if symbol_a == symbol_b:
        return {"ticker_a": symbol_a, "ticker_b": symbol_b, "error": "Same ticker for both legs", "cointegrated": False}
    if n < MIN_OBSERVATIONS:
        return {"ticker_a": symbol_a, "ticker_b": symbol_b, "n_observations": n,
                "error": f"Insufficient overlap: {n} obs (need {MIN_OBSERVATIONS}+)", "cointegrated": False}

    a = np.array(a_list, dtype=float)
    b = np.array(b_list, dtype=float)
    if (a <= 0).any() or (b <= 0).any():
        return {"ticker_a": symbol_a, "ticker_b": symbol_b, "n_observations": n,
                "error": "Non-positive prices found (cannot take log)", "cointegrated": False}
    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return {"ticker_a": symbol_a, "ticker_b": symbol_b, "n_observations": n,
                "error": "Degenerate: constant price series", "cointegrated": False}

    log_a = np.log(a)
    log_b = np.log(b)
    hedge_ratio = _tls_hedge_ratio(log_a, log_b)
    if not math.isfinite(hedge_ratio) or abs(hedge_ratio) < 1e-9:
        return {"ticker_a": symbol_a, "ticker_b": symbol_b, "n_observations": n,
                "error": "Hedge ratio degenerate", "cointegrated": False}

    spread = compute_spread(a, b, hedge_ratio)
    if len(spread) < max(zscore_window, 30):
        return {"ticker_a": symbol_a, "ticker_b": symbol_b, "n_observations": n,
                "error": "Insufficient spread observations after alignment", "cointegrated": False}

    eg = engle_granger_test(spread)
    p_value = eg.get("p_value")

    recent_spread = spread[-zscore_window:]
    mu = float(np.mean(recent_spread))
    sigma = float(np.std(recent_spread, ddof=1)) if len(recent_spread) > 1 else 0.0
    current_z: float | None
    if sigma > 1e-9 and math.isfinite(spread[-1]):
        current_z = float((spread[-1] - mu) / sigma)
    else:
        current_z = None

    half_life = _ou_half_life(spread)
    a_returns = np.diff(log_a)
    b_returns = np.diff(log_b)
    stability_info = _rolling_correlation_stability(a_returns, b_returns, window=stability_window)

    reasons: list[str] = []
    p_ok = p_value is not None and p_value < COINTEGRATION_P_THRESHOLD
    hl_ok = half_life is not None and MIN_HALF_LIFE_DAYS < half_life < MAX_HALF_LIFE_DAYS
    stab = stability_info.get("stability")
    stab_ok = stab is not None and stab > MIN_STABILITY

    if not p_ok:
        reasons.append("ADF test unavailable" if p_value is None
                       else f"Failed cointegration (ADF p={p_value:.3f} ≥ {COINTEGRATION_P_THRESHOLD})")
    if not hl_ok:
        if half_life is None:
            reasons.append("Spread not mean-reverting (AR(1) coefficient ≥ 0)")
        elif half_life <= MIN_HALF_LIFE_DAYS:
            reasons.append(f"Half-life too short ({half_life:.1f}d)")
        else:
            reasons.append(f"Half-life too long ({half_life:.1f}d > {MAX_HALF_LIFE_DAYS:.0f}d)")
    if not stab_ok:
        reasons.append("Stability test insufficient data" if stab is None
                       else f"Unstable correlation (stability={stab:.2f} ≤ {MIN_STABILITY:.2f})")

    cointegrated = bool(p_ok and hl_ok and stab_ok)
    if cointegrated and not reasons:
        reasons.append("Cointegrated, mean-reverting in tradable window, stable correlation")

    trade_signal = "hold"
    if cointegrated and current_z is not None:
        if current_z > ENTRY_ZSCORE:
            trade_signal = "short_spread"
        elif current_z < -ENTRY_ZSCORE:
            trade_signal = "long_spread"

    share_ratio_at_close: float | None = None
    if math.isfinite(hedge_ratio) and b[-1] > 0:
        share_ratio_at_close = float(hedge_ratio * a[-1] / b[-1])

    return {
        "ticker_a": symbol_a,
        "ticker_b": symbol_b,
        "n_observations": n,
        "hedge_ratio": round(float(hedge_ratio), 4),
        "hedge_ratio_method": "total_least_squares_log_prices",
        "share_ratio_at_close": _clean(round(share_ratio_at_close, 4)) if share_ratio_at_close is not None else None,
        "cointegration": {
            "p_value": _clean(round(p_value, 4)) if p_value is not None else None,
            "test_statistic": (_clean(round(eg.get("test_statistic", float("nan")), 3))
                               if eg.get("test_statistic") is not None else None),
            "critical_values": eg.get("critical_values"),
            "n_lags": eg.get("n_lags"),
            "method": eg.get("method"),
            "significant_at_5pct": bool(p_ok),
        },
        "half_life_days": _clean(round(half_life, 2)) if half_life is not None else None,
        "spread": {
            "current_value": _clean(round(float(spread[-1]), 6)),
            "rolling_mean": round(mu, 6),
            "rolling_std": round(sigma, 6),
            "current_zscore": _clean(round(current_z, 3)) if current_z is not None else None,
            "window": zscore_window,
        },
        "stability": {
            "rolling_correlation_mean": (_clean(round(stability_info["mean_corr"], 3))
                                         if stability_info["mean_corr"] is not None else None),
            "rolling_correlation_std": (_clean(round(stability_info["std_corr"], 3))
                                        if stability_info["std_corr"] is not None else None),
            "stability_score": (_clean(round(stab, 3)) if stab is not None else None),
            "n_windows": stability_info["n_windows"],
        },
        "cointegrated": cointegrated,
        "trade_signal": trade_signal,
        "reasons": reasons,
    }


def find_cointegrated_pairs(
    prices: dict[str, list[float]],
    *,
    candidates: list[tuple[str, str]] | None = None,
    zscore_window: int = ZSCORE_WINDOW,
    stability_window: int = STABILITY_WINDOW,
    cointegrated_only: bool = True,
) -> dict:
    """Screen a universe of supplied price series for cointegrated pairs.

    `prices`: {symbol: [close, ...]} — series are assumed to share a trading
    calendar; each pair is aligned to its common length from the most recent
    end. `candidates`: optional explicit pair list; default is all unique
    unordered pairs. Returns pairs sorted by ADF p-value ascending.
    """
    symbols = list(prices.keys())
    pairs = candidates if candidates is not None else list(itertools.combinations(symbols, 2))

    results: list[dict] = []
    for sa, sb in pairs:
        if sa not in prices or sb not in prices:
            continue
        res = compute_spread_signal(prices[sa], prices[sb], symbol_a=sa, symbol_b=sb,
                                    zscore_window=zscore_window, stability_window=stability_window)
        results.append(res)

    def _p(r: dict):
        p = (r.get("cointegration") or {}).get("p_value")
        return p if p is not None else 1.0

    results.sort(key=_p)
    selected = [r for r in results if r.get("cointegrated")] if cointegrated_only else results

    return {
        "n_evaluated": len(results),
        "n_cointegrated": sum(1 for r in results if r.get("cointegrated")),
        "pairs": selected,
    }
