"""
quant/pairs.py — Pair-trade analytics for L/S construction.

Implements the four math primitives a real PM looks at before sizing a pair:

  1. Hedge ratio via Total Least Squares on log prices. OLS slope is biased
     toward zero when both legs have noise (errors-in-variables / attenuation
     bias); TLS solves the orthogonal regression and is the textbook fix.
  2. Engle-Granger cointegration: ADF test on the log-price spread. Null is
     "spread is non-stationary" (no cointegration). Reject at p<0.05 to
     trade the pair.
  3. Ornstein-Uhlenbeck half-life via AR(1) regression on the differenced
     spread. Tells you how long mean reversion actually takes — a spread
     that's "cointegrated" with a 200-day half-life will eat your funding
     before it converges.
  4. Rolling correlation stability — the relationship can be cointegrated
     in-sample and structurally broken out-of-sample (sector rotation,
     regime shift). We measure stability as `1 - std(rolling 60d corr)`.

All four must pass before we call a pair tradable.
"""

from __future__ import annotations

import math
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    from statsmodels.tsa.stattools import adfuller  # type: ignore
    STATSMODELS_AVAILABLE = True
except ImportError:
    STATSMODELS_AVAILABLE = False
    logger.warning("statsmodels not installed — pair cointegration disabled")


# Pair-trading thresholds. Documented so a PM can audit / override.
MIN_OBSERVATIONS = 126           # ~6 months daily — below this, ADF + half-life are noise
COINTEGRATION_P_THRESHOLD = 0.05  # reject the unit-root null at 5%
MIN_HALF_LIFE_DAYS = 1.0          # below: not really a pair, just noise around zero
MAX_HALF_LIFE_DAYS = 60.0         # above: too slow — funding cost > expected convergence
MIN_STABILITY = 0.5               # below: rolling corr is too unstable to bet on
ZSCORE_WINDOW = 60                # 3-month spread z-score window
STABILITY_WINDOW = 60             # 3-month rolling-correlation stability window
ENTRY_ZSCORE = 2.0                # |z| above this triggers a long_spread / short_spread call


def _clean(val: Any) -> Any:
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def _align_on_dates(
    a_history: list[dict], b_history: list[dict]
) -> tuple[list[float], list[float], list[str]]:
    """
    Align two price histories on the intersection of trading dates.
    Each history is a list of {date, close} dicts. Returns aligned
    (a_closes, b_closes, dates) sorted ascending by date.
    """
    a_map: dict[str, float] = {}
    for bar in a_history:
        d = bar.get("date")
        c = bar.get("close")
        if d is None or c is None:
            continue
        try:
            a_map[d] = float(c)
        except (TypeError, ValueError):
            continue
    b_map: dict[str, float] = {}
    for bar in b_history:
        d = bar.get("date")
        c = bar.get("close")
        if d is None or c is None:
            continue
        try:
            b_map[d] = float(c)
        except (TypeError, ValueError):
            continue
    common = sorted(set(a_map.keys()) & set(b_map.keys()))
    return [a_map[d] for d in common], [b_map[d] for d in common], common


def _tls_hedge_ratio(a: np.ndarray, b: np.ndarray) -> float:
    """
    Total Least Squares slope of `a ~ β·b` via SVD of the centered design
    matrix [b_centered, a_centered]. The smallest right singular vector is
    perpendicular to the orthogonal-regression line; the slope is then
    -v[0] / v[1].

    OLS biases β toward zero when b has noise (attenuation bias). TLS is
    the unbiased estimator when both legs have measurement noise — which
    is always true for two market prices.
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
    """
    Mean-reversion half-life via AR(1) regression on the differenced spread:

        Δs_t = a + b · s_{t-1} + ε_t

    The discrete equivalent of the Ornstein-Uhlenbeck process gives
    θ = -b (mean-reversion speed), half_life = ln(2) / θ = -ln(2) / b.

    Returns None when b ≥ 0 (no mean reversion) or when the fit degenerates.
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
    """
    Stability = 1 - std(rolling correlation). High stability means the
    relationship is structurally consistent, not regime-dependent.
    Returns dict with stability score, mean/std of rolling correlations,
    and number of windows used.
    """
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
    return {
        "stability": stability,
        "mean_corr": mean_c,
        "std_corr": std_c,
        "n_windows": len(rolling),
    }


def compute_spread(
    a_closes: np.ndarray, b_closes: np.ndarray, hedge_ratio: float
) -> np.ndarray:
    """
    Log-price spread: s_t = log(P_a) - β · log(P_b).
    Scale-invariant and matches the formulation tested by Engle-Granger.
    """
    a = np.asarray(a_closes, dtype=float)
    b = np.asarray(b_closes, dtype=float)
    return np.log(a) - hedge_ratio * np.log(b)


def engle_granger_test(spread: np.ndarray) -> dict:
    """
    ADF test on the spread series. Null H0: spread has a unit root (NOT
    cointegrated). Reject at p<0.05 → series are cointegrated.

    Returns p_value, test_statistic, critical_values dict. p_value is None
    when statsmodels isn't installed or the test errors out.
    """
    if not STATSMODELS_AVAILABLE:
        return {"p_value": None, "test_statistic": None, "method": "unavailable"}

    spread_clean = np.asarray(spread, dtype=float)
    spread_clean = spread_clean[np.isfinite(spread_clean)]
    if len(spread_clean) < 30:
        return {
            "p_value": None,
            "test_statistic": None,
            "method": "engle_granger",
            "error": "insufficient_data",
        }

    try:
        result = adfuller(spread_clean, regression="c", autolag="AIC")
        return {
            "p_value": float(result[1]),
            "test_statistic": float(result[0]),
            "critical_values": {k: float(v) for k, v in result[4].items()},
            "n_lags": int(result[2]),
            "method": "engle_granger",
        }
    except Exception as e:  # noqa: BLE001 — statsmodels can throw varied errors
        logger.warning(f"ADF test failed: {e}")
        return {
            "p_value": None,
            "test_statistic": None,
            "method": "engle_granger",
            "error": str(e),
        }


def analyze_pair(
    ticker_a: str,
    ticker_b: str,
    period: str = "1y",
    zscore_window: int = ZSCORE_WINDOW,
    stability_window: int = STABILITY_WINDOW,
) -> dict:
    """
    End-to-end pair analysis. Fetches both legs, aligns on common dates,
    computes hedge ratio (TLS), cointegration p-value (Engle-Granger ADF),
    spread z-score, OU half-life, rolling-correlation stability, and
    issues a discrete trade signal.

    A pair is `cointegrated=True` only when ALL four checks pass:
      - ADF p-value < COINTEGRATION_P_THRESHOLD
      - Half-life ∈ (MIN_HALF_LIFE_DAYS, MAX_HALF_LIFE_DAYS)
      - Stability > MIN_STABILITY
      - Sufficient observations (≥ MIN_OBSERVATIONS)

    Trade signal:
      - |z| > ENTRY_ZSCORE → long_spread (long A, short β·B) or short_spread
      - else → hold

    Note: `hedge_ratio` is the *cointegration coefficient* on log prices,
    NOT a share ratio. To convert to shares for execution-sized neutrality
    at current prices: shares_b = shares_a * (price_a / price_b) * hedge_ratio.
    Surfaced as `share_ratio_at_close` in the return for convenience.
    """
    from data.market_client import MarketDataClient
    mc = MarketDataClient()

    if ticker_a == ticker_b:
        return {
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "error": "Same ticker for both legs",
            "cointegrated": False,
        }

    a_hist = mc.get_price_history(ticker_a, period=period)
    b_hist = mc.get_price_history(ticker_b, period=period)
    if not a_hist:
        return {
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "error": f"No price data for {ticker_a}",
            "cointegrated": False,
        }
    if not b_hist:
        return {
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "error": f"No price data for {ticker_b}",
            "cointegrated": False,
        }

    a_list, b_list, dates = _align_on_dates(a_hist, b_hist)
    n = len(a_list)
    if n < MIN_OBSERVATIONS:
        return {
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "n_observations": n,
            "error": f"Insufficient overlap: {n} obs (need {MIN_OBSERVATIONS}+)",
            "cointegrated": False,
        }

    a = np.array(a_list, dtype=float)
    b = np.array(b_list, dtype=float)

    if (a <= 0).any() or (b <= 0).any():
        return {
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "n_observations": n,
            "error": "Non-positive prices found (cannot take log)",
            "cointegrated": False,
        }

    if np.std(a) < 1e-9 or np.std(b) < 1e-9:
        return {
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "n_observations": n,
            "error": "Degenerate: constant price series",
            "cointegrated": False,
        }

    log_a = np.log(a)
    log_b = np.log(b)

    hedge_ratio = _tls_hedge_ratio(log_a, log_b)
    if not math.isfinite(hedge_ratio) or abs(hedge_ratio) < 1e-9:
        return {
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "n_observations": n,
            "error": "Hedge ratio degenerate",
            "cointegrated": False,
        }

    spread = compute_spread(a, b, hedge_ratio)
    if len(spread) < max(zscore_window, 30):
        return {
            "ticker_a": ticker_a,
            "ticker_b": ticker_b,
            "n_observations": n,
            "error": "Insufficient spread observations after alignment",
            "cointegrated": False,
        }

    # Engle-Granger ADF on the spread
    eg = engle_granger_test(spread)
    p_value = eg.get("p_value")

    # Z-score over the last zscore_window observations
    recent_spread = spread[-zscore_window:]
    mu = float(np.mean(recent_spread))
    sigma = float(np.std(recent_spread, ddof=1)) if len(recent_spread) > 1 else 0.0
    current_z: float | None
    if sigma > 1e-9 and math.isfinite(spread[-1]):
        current_z = float((spread[-1] - mu) / sigma)
    else:
        current_z = None

    # OU half-life on the full spread series
    half_life = _ou_half_life(spread)

    # Stability via rolling correlation of log-returns
    a_returns = np.diff(log_a)
    b_returns = np.diff(log_b)
    stability_info = _rolling_correlation_stability(a_returns, b_returns, window=stability_window)

    # Decision: ALL four must pass
    reasons: list[str] = []
    p_ok = p_value is not None and p_value < COINTEGRATION_P_THRESHOLD
    hl_ok = half_life is not None and MIN_HALF_LIFE_DAYS < half_life < MAX_HALF_LIFE_DAYS
    stab = stability_info.get("stability")
    stab_ok = stab is not None and stab > MIN_STABILITY

    if not p_ok:
        if p_value is None:
            reasons.append("ADF test unavailable")
        else:
            reasons.append(f"Failed cointegration (ADF p={p_value:.3f} ≥ {COINTEGRATION_P_THRESHOLD})")
    if not hl_ok:
        if half_life is None:
            reasons.append("Spread not mean-reverting (AR(1) coefficient ≥ 0)")
        elif half_life <= MIN_HALF_LIFE_DAYS:
            reasons.append(f"Half-life too short ({half_life:.1f}d)")
        else:
            reasons.append(f"Half-life too long ({half_life:.1f}d > {MAX_HALF_LIFE_DAYS:.0f}d)")
    if not stab_ok:
        if stab is None:
            reasons.append("Stability test insufficient data")
        else:
            reasons.append(f"Unstable correlation (stability={stab:.2f} ≤ {MIN_STABILITY:.2f})")

    cointegrated = bool(p_ok and hl_ok and stab_ok)
    if cointegrated and not reasons:
        reasons.append("Cointegrated, mean-reverting in tradable window, stable correlation")

    # Trade signal
    trade_signal = "hold"
    if cointegrated and current_z is not None:
        if current_z > ENTRY_ZSCORE:
            trade_signal = "short_spread"   # spread overshot up → short A, long β·B
        elif current_z < -ENTRY_ZSCORE:
            trade_signal = "long_spread"    # spread overshot down → long A, short β·B

    # Convert log-price coefficient to a share ratio at current prices
    share_ratio_at_close: float | None = None
    if math.isfinite(hedge_ratio) and b[-1] > 0:
        share_ratio_at_close = float(hedge_ratio * a[-1] / b[-1])

    return {
        "ticker_a": ticker_a,
        "ticker_b": ticker_b,
        "period": period,
        "n_observations": n,
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "hedge_ratio": round(float(hedge_ratio), 4),
        "hedge_ratio_method": "total_least_squares_log_prices",
        "share_ratio_at_close": _clean(round(share_ratio_at_close, 4)) if share_ratio_at_close is not None else None,
        "cointegration": {
            "p_value": _clean(round(p_value, 4)) if p_value is not None else None,
            "test_statistic": (
                _clean(round(eg.get("test_statistic", float("nan")), 3))
                if eg.get("test_statistic") is not None
                else None
            ),
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
            "rolling_correlation_mean": (
                _clean(round(stability_info["mean_corr"], 3))
                if stability_info["mean_corr"] is not None else None
            ),
            "rolling_correlation_std": (
                _clean(round(stability_info["std_corr"], 3))
                if stability_info["std_corr"] is not None else None
            ),
            "stability_score": (
                _clean(round(stab, 3)) if stab is not None else None
            ),
            "n_windows": stability_info["n_windows"],
        },
        "cointegrated": cointegrated,
        "trade_signal": trade_signal,
        "reasons": reasons,
        "thresholds": {
            "cointegration_p": COINTEGRATION_P_THRESHOLD,
            "min_half_life_days": MIN_HALF_LIFE_DAYS,
            "max_half_life_days": MAX_HALF_LIFE_DAYS,
            "min_stability": MIN_STABILITY,
            "entry_zscore": ENTRY_ZSCORE,
            "min_observations": MIN_OBSERVATIONS,
        },
    }
