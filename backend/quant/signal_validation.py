"""
Signal Validation — measure agent predictive power and optimize weights.

IC, ICIR, hit rate by conviction, alpha decay, weight optimization.
Pure math. No LLM calls.
"""

import numpy as np
import math
from scipy.stats import spearmanr
import logging

logger = logging.getLogger(__name__)

DIRECTION_MAP = {
    "strong_bearish": -2, "bearish": -1, "neutral": 0,
    "bullish": 1, "strong_bullish": 2,
}


def _clean(val):
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def compute_ic(
    signal_directions: list[str],
    signal_convictions: list[int],
    forward_returns: list[float],
) -> float | None:
    """
    Information Coefficient = Spearman rank correlation between
    signal strength (direction * conviction) and forward returns.
    IC > 0.05 = useful. IC > 0.10 = very strong.
    """
    if len(signal_directions) < 10:
        return None

    n = min(len(signal_directions), len(forward_returns))
    signals = [
        DIRECTION_MAP.get(d, 0) * (c / 100)
        for d, c in zip(signal_directions[:n], signal_convictions[:n])
    ]
    returns = forward_returns[:n]

    corr, _ = spearmanr(signals, returns)
    return _clean(round(float(corr), 4))


def compute_forward_returns_aligned(
    signals: list[dict],
    prices_by_ticker: dict[str, list[dict]],
    horizon_days: int,
    execution_lag_days: int = 1,
) -> list[dict]:
    """
    Build a list of {signal, forward_return} pairs where each forward return
    is measured strictly AFTER the signal date plus an execution lag.

    Why this matters: the existing `compute_ic(signals, returns)` API
    aligns by list index — implicitly assuming all signals share the same
    timeline and the caller's `forward_returns` list already starts at the
    "right" point. In practice, signals are timestamped, and IC computed
    against same-day or unlagged returns is biased by leakage. This helper
    fixes that by lookup-from-date.

    `signals` is a list of dicts with at least:
        {ticker, direction, conviction, signal_date}     (ISO date)
    `prices_by_ticker` is { ticker -> [{date, close}, ...] } sorted ascending.

    Returns: [{signal, forward_return, signal_date, fill_date, target_date}]
    """
    from datetime import datetime, timedelta

    out: list[dict] = []
    for sig in signals:
        tk = (sig.get("ticker") or "").upper()
        bars = prices_by_ticker.get(tk)
        if not bars:
            continue
        sd_raw = sig.get("signal_date")
        if not sd_raw:
            continue
        try:
            sd = datetime.fromisoformat(str(sd_raw).split("T")[0]).date()
        except Exception:
            continue

        # Find the first bar STRICTLY AFTER sd + lag (execution day).
        fill_target = sd + timedelta(days=execution_lag_days)
        target_target = sd + timedelta(days=execution_lag_days + horizon_days)

        fill_idx: int | None = None
        target_idx: int | None = None
        for i, bar in enumerate(bars):
            try:
                bd = datetime.fromisoformat(str(bar["date"]).split("T")[0]).date()
            except Exception:
                continue
            if fill_idx is None and bd >= fill_target:
                fill_idx = i
            if target_idx is None and bd >= target_target:
                target_idx = i
                break

        if fill_idx is None or target_idx is None or target_idx <= fill_idx:
            continue

        fill_px = float(bars[fill_idx]["close"])
        target_px = float(bars[target_idx]["close"])
        if fill_px <= 0:
            continue
        fwd_ret = (target_px - fill_px) / fill_px

        out.append({
            "signal": sig,
            "forward_return": fwd_ret,
            "signal_date": str(bars[max(0, fill_idx - 1)]["date"]),
            "fill_date": str(bars[fill_idx]["date"]),
            "target_date": str(bars[target_idx]["date"]),
        })
    return out


def compute_ic_aligned(
    signals: list[dict],
    prices_by_ticker: dict[str, list[dict]],
    horizon_days: int = 5,
    execution_lag_days: int = 1,
) -> dict:
    """
    Date-aligned IC: signals are zipped to forward returns measured AFTER
    each signal's own date, with an execution lag. Returns IC + sample
    metadata so the caller can reject thin samples.
    """
    pairs = compute_forward_returns_aligned(
        signals, prices_by_ticker, horizon_days, execution_lag_days
    )
    if len(pairs) < 10:
        return {
            "ic": None, "n": len(pairs),
            "horizon_days": horizon_days,
            "execution_lag_days": execution_lag_days,
            "low_sample": True,
        }

    directions = [p["signal"].get("direction", "neutral") for p in pairs]
    convictions = [int(p["signal"].get("conviction", 0) or 0) for p in pairs]
    rets = [p["forward_return"] for p in pairs]

    ic = compute_ic(directions, convictions, rets)
    return {
        "ic": ic,
        "n": len(pairs),
        "horizon_days": horizon_days,
        "execution_lag_days": execution_lag_days,
        "low_sample": len(pairs) < 30,
    }


def compute_icir(ic_series: list[float]) -> float | None:
    """IC Information Ratio = mean(IC) / std(IC). ICIR > 0.5 = good."""
    clean = [ic for ic in ic_series if ic is not None]
    if len(clean) < 5:
        return None
    std = float(np.std(clean, ddof=1))
    if std == 0:
        return None
    return _clean(round(float(np.mean(clean)) / std, 3))


def hit_rate_by_conviction(
    signal_directions: list[str],
    signal_convictions: list[int],
    forward_returns: list[float],
    bins: list[tuple] = [(0, 30), (30, 50), (50, 70), (70, 90), (90, 100)],
) -> list[dict]:
    """Hit rate bucketed by conviction. High conviction must have higher hit rates."""
    n = min(len(signal_directions), len(forward_returns))
    results = []

    for lo, hi in bins:
        indices = [
            i for i in range(n)
            if lo <= signal_convictions[i] < hi
        ]
        if not indices:
            results.append({"bucket": f"{lo}-{hi}", "hit_rate": None, "count": 0, "avg_return": None})
            continue

        hits = 0
        rets = []
        for i in indices:
            d = DIRECTION_MAP.get(signal_directions[i], 0)
            r = forward_returns[i]
            if (d > 0 and r > 0) or (d < 0 and r < 0) or (d == 0):
                hits += 1
            rets.append(r)

        results.append({
            "bucket": f"{lo}-{hi}",
            "hit_rate": round(hits / len(indices) * 100, 1),
            "count": len(indices),
            "avg_return": _clean(round(float(np.mean(rets)) * 100, 2)),
        })

    return results


def compute_alpha_decay(
    signal_directions: list[str],
    signal_convictions: list[int],
    price_series: list[float],
    horizons: list[int] = [1, 2, 5, 10, 21],
) -> list[dict]:
    """IC at each forward horizon. Where IC drops = signal half-life."""
    n = len(signal_directions)
    results = []

    for h in horizons:
        if n < h + 10:
            results.append({"horizon": h, "ic": None})
            continue

        forward_returns = [
            (price_series[i + h] - price_series[i]) / price_series[i]
            for i in range(n)
            if i + h < len(price_series)
        ]

        ic = compute_ic(
            signal_directions[:len(forward_returns)],
            signal_convictions[:len(forward_returns)],
            forward_returns,
        )
        results.append({"horizon": h, "ic": ic})

    return results


def fit_decay_half_life(decay_curve: list[dict]) -> dict:
    """
    Fit IC(h) = IC0 * exp(-h / lambda)  via log-linear regression on
    ln(IC) ~ ln(IC0) - h / lambda.

    Returns:
        {ic_0: initial IC, half_life_days: ln(2)*lambda, lambda_days,
         r_squared, recommended_max_holding_days}

    The recommended max holding is the horizon at which IC drops below 0.02
    (effectively noise) given the fitted curve. Caller can compare to its
    actual holding windows: if you're holding past the half-life, you're
    holding past where the system thinks the signal stopped predicting.
    """
    pts = [(int(d["horizon"]), float(d["ic"])) for d in decay_curve if d.get("ic") is not None and d["ic"] > 0]
    if len(pts) < 3:
        return {"error": "Need 3+ positive-IC points to fit decay"}

    horizons = np.array([p[0] for p in pts], dtype=float)
    ics = np.array([p[1] for p in pts], dtype=float)
    log_ics = np.log(ics)

    # Log-linear fit
    A = np.vstack([horizons, np.ones_like(horizons)]).T
    slope, intercept = np.linalg.lstsq(A, log_ics, rcond=None)[0]
    if slope >= 0:
        return {"error": "IC not decaying (slope >= 0)"}

    lam = -1.0 / float(slope)
    ic_0 = float(np.exp(intercept))
    half_life = lam * float(np.log(2))

    # R-squared
    pred = slope * horizons + intercept
    ss_res = float(np.sum((log_ics - pred) ** 2))
    ss_tot = float(np.sum((log_ics - np.mean(log_ics)) ** 2))
    r_sq = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Horizon where IC drops below 0.02 (noise threshold)
    if ic_0 > 0.02:
        days_to_noise = lam * float(np.log(ic_0 / 0.02))
    else:
        days_to_noise = 0.0

    return {
        "ic_0": round(ic_0, 4),
        "half_life_days": round(half_life, 2),
        "lambda_days": round(lam, 2),
        "r_squared": round(r_sq, 3),
        "recommended_max_holding_days": round(max(0.0, days_to_noise), 1),
        "fit_points": len(pts),
    }


def optimize_weights_ic(
    agent_ics: dict[str, float],
) -> dict[str, float]:
    """
    IC-weighted optimization: weight_i = max(0, IC_i) / sum(max(0, IC_j)).
    Agents with negative IC get 0 weight.
    """
    positive = {k: max(0, v) for k, v in agent_ics.items() if v is not None}
    total = sum(positive.values())
    if total == 0:
        # Equal weight fallback
        n = len(agent_ics)
        return {k: round(1 / n, 3) for k in agent_ics}

    return {k: round(v / total, 3) for k, v in positive.items()}


def agent_report_card(
    agent_name: str,
    signal_directions: list[str],
    signal_convictions: list[int],
    forward_returns_5d: list[float],
    forward_returns_21d: list[float],
    price_series: list[float],
) -> dict:
    """Comprehensive per-agent evaluation."""
    ic_5d = compute_ic(signal_directions, signal_convictions, forward_returns_5d)
    ic_21d = compute_ic(signal_directions, signal_convictions, forward_returns_21d)

    n = min(len(signal_directions), len(forward_returns_5d))
    hits = sum(
        1 for i in range(n)
        if (DIRECTION_MAP.get(signal_directions[i], 0) > 0 and forward_returns_5d[i] > 0)
        or (DIRECTION_MAP.get(signal_directions[i], 0) < 0 and forward_returns_5d[i] < 0)
    )

    conviction_when_correct = []
    conviction_when_wrong = []
    for i in range(n):
        d = DIRECTION_MAP.get(signal_directions[i], 0)
        r = forward_returns_5d[i]
        if (d > 0 and r > 0) or (d < 0 and r < 0):
            conviction_when_correct.append(signal_convictions[i])
        else:
            conviction_when_wrong.append(signal_convictions[i])

    decay = compute_alpha_decay(signal_directions, signal_convictions, price_series)
    best_horizon = max(decay, key=lambda x: (x["ic"] or -999))
    half_life = fit_decay_half_life(decay)

    return {
        "agent_name": agent_name,
        "total_signals": n,
        "ic_5d": ic_5d,
        "ic_21d": ic_21d,
        "hit_rate": round(hits / n * 100, 1) if n > 0 else None,
        "hit_rate_by_conviction": hit_rate_by_conviction(signal_directions, signal_convictions, forward_returns_5d),
        "alpha_decay": decay,
        "decay_half_life": half_life,
        "best_horizon_days": best_horizon["horizon"] if best_horizon["ic"] else None,
        "avg_conviction_correct": round(float(np.mean(conviction_when_correct)), 1) if conviction_when_correct else None,
        "avg_conviction_wrong": round(float(np.mean(conviction_when_wrong)), 1) if conviction_when_wrong else None,
    }
