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

    return {
        "agent_name": agent_name,
        "total_signals": n,
        "ic_5d": ic_5d,
        "ic_21d": ic_21d,
        "hit_rate": round(hits / n * 100, 1) if n > 0 else None,
        "hit_rate_by_conviction": hit_rate_by_conviction(signal_directions, signal_convictions, forward_returns_5d),
        "alpha_decay": decay,
        "best_horizon_days": best_horizon["horizon"] if best_horizon["ic"] else None,
        "avg_conviction_correct": round(float(np.mean(conviction_when_correct)), 1) if conviction_when_correct else None,
        "avg_conviction_wrong": round(float(np.mean(conviction_when_wrong)), 1) if conviction_when_wrong else None,
    }
