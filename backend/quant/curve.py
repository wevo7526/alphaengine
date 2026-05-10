"""
quant/curve.py — Treasury yield curve construction & rate-risk analytics.

What's here:

  1. get_curve(date=None)
       Pulls all available CMT (constant-maturity Treasury) yields from FRED
       at 11 tenors (1M through 30Y) and returns a sorted curve. Cubic spline
       interpolation fills missing tenors so downstream consumers don't need
       to handle gaps.

  2. curve_shape(curve)
       Standard curve summary: level (5Y as the canonical midpoint), slope
       (10Y - 2Y, the recession indicator), long-end slope (30Y - 10Y), and
       a 2-5-10 butterfly (curvature).

  3. curve_regime(history_days=120)
       Classifies the last `history_days` of curve evolution into one of
       five regimes: bull/bear × steepener/flattener, or "stable" when the
       move is below threshold. These are the four canonical macro PM
       framings: a bear steepener (rates up, long end faster) is a very
       different trade than a bear flattener (rates up, short end faster).

  4. key_rate_durations(asset_returns, history_days=252, tenors=...)
       Empirical rate-beta regression: how does the asset move when yields
       at {2Y, 5Y, 10Y, 30Y} move? Coefficients are estimated jointly via
       OLS so a 10Y-sensitive name (TLT) shows ~ -7 to -10 in β_10y and a
       low-rate-beta equity shows near zero. For pure bonds this approximates
       a key-rate duration; for equities it's a rate sensitivity coefficient.

All math is computed from live FRED data — no hardcoded yield levels or
beta tables. Winsorized at the 1%/99% percentile to absorb data spikes.
"""

from __future__ import annotations

import math
import logging
from datetime import datetime, date as _date_type
from typing import Any

import numpy as np
from scipy.interpolate import CubicSpline

logger = logging.getLogger(__name__)

# FRED series → tenor in years. CMT (constant-maturity) yields are the
# textbook curve inputs — they're synthetic but stable and unaffected by
# the on-the-run premium that distorts cash Treasury yields.
FRED_TENORS: list[tuple[str, float]] = [
    ("DGS1MO", 1 / 12),
    ("DGS3MO", 3 / 12),
    ("DGS6MO", 6 / 12),
    ("DGS1", 1.0),
    ("DGS2", 2.0),
    ("DGS3", 3.0),
    ("DGS5", 5.0),
    ("DGS7", 7.0),
    ("DGS10", 10.0),
    ("DGS20", 20.0),
    ("DGS30", 30.0),
]

# Default key-rate tenors for the rate-beta regression — the four points
# that span the yield curve and are highly liquid. 7Y / 3Y excluded because
# they're near-redundant with 5Y / 2Y under PCA.
DEFAULT_KEY_RATE_TENORS = [2.0, 5.0, 10.0, 30.0]

# Regime classification thresholds (in basis points of move over the window)
REGIME_STABLE_BP = 25.0  # below this on both axes = "stable"


def _clean(val: Any) -> Any:
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val


def _winsorize(arr: np.ndarray, lo_pct: float = 1.0, hi_pct: float = 99.0) -> np.ndarray:
    """Clip extreme values to the [lo_pct, hi_pct] percentile range."""
    finite = arr[np.isfinite(arr)]
    if finite.size < 10:
        return arr
    lo = float(np.percentile(finite, lo_pct))
    hi = float(np.percentile(finite, hi_pct))
    return np.clip(arr, lo, hi)


def get_curve(date: _date_type | str | None = None) -> dict:
    """
    Return the latest (or as-of-date) yield curve from FRED CMT series.

    Cubic spline interpolation fills any missing tenor so the curve is
    always returned at all 11 standard points. The interpolation flag in
    the response distinguishes observed from filled tenors.

    Returns:
        {
            "as_of": "YYYY-MM-DD" (latest common date),
            "points": [{tenor_years, yield_pct, source: "observed"|"interpolated"}],
            "level_5y": float, "slope_10y2y": float, "butterfly_2y5y10y": float,
            "method": "fred_cmt_cubic_spline",
        }
    """
    from data.fred_client import FREDDataClient
    fred = FREDDataClient()

    observed: list[tuple[float, float]] = []  # (tenor_yrs, yield_pct)
    latest_dates: list[str] = []

    if date is None:
        # Latest available — pull single indicator per series
        for series_id, tenor in FRED_TENORS:
            try:
                data = fred.get_single_indicator(series_id)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"FRED single {series_id}: {e}")
                continue
            if not data:
                continue
            val = data.get("value")
            if val is None:
                continue
            try:
                y = float(val)
            except (TypeError, ValueError):
                continue
            if 0 < y < 30:  # sanity: yield in [0, 30]%
                observed.append((tenor, y))
                d = data.get("date")
                if d:
                    latest_dates.append(str(d))
    else:
        # Historical curve at a specific date — need series history
        target = date.isoformat() if isinstance(date, _date_type) else str(date)
        for series_id, tenor in FRED_TENORS:
            try:
                hist = fred.get_series_history(series_id, lookback_days=365)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"FRED hist {series_id}: {e}")
                continue
            if not hist:
                continue
            # Find observation on or just before target date
            matching = [h for h in hist if h.get("date") <= target]
            if not matching:
                continue
            latest_obs = max(matching, key=lambda h: h["date"])
            val = latest_obs.get("value")
            if val is None:
                continue
            try:
                y = float(val)
            except (TypeError, ValueError):
                continue
            if 0 < y < 30:
                observed.append((tenor, y))
                latest_dates.append(latest_obs["date"])

    if len(observed) < 2:
        return {
            "as_of": None,
            "points": [],
            "error": "Insufficient FRED data — fewer than 2 tenors available",
            "method": "fred_cmt_cubic_spline",
        }

    observed.sort(key=lambda x: x[0])
    obs_tenors = np.array([p[0] for p in observed], dtype=float)
    obs_yields = np.array([p[1] for p in observed], dtype=float)

    # Cubic spline interpolation; fall back to linear if fewer than 4 points
    target_tenors = np.array([t for _, t in FRED_TENORS], dtype=float)
    obs_tenor_set = {round(t, 4) for t in obs_tenors}

    if len(observed) >= 4:
        try:
            spline = CubicSpline(obs_tenors, obs_yields, bc_type="natural", extrapolate=True)
            interpolated_yields = spline(target_tenors)
        except (ValueError, np.linalg.LinAlgError) as e:
            logger.warning(f"Cubic spline failed ({e}); using linear interpolation")
            interpolated_yields = np.interp(target_tenors, obs_tenors, obs_yields)
    else:
        interpolated_yields = np.interp(target_tenors, obs_tenors, obs_yields)

    points: list[dict] = []
    for tenor, y in zip(target_tenors, interpolated_yields):
        is_observed = round(tenor, 4) in obs_tenor_set
        if is_observed:
            # Use exact observed value (avoid spline rounding noise)
            for ot, oy in zip(obs_tenors, obs_yields):
                if abs(ot - tenor) < 1e-6:
                    y = float(oy)
                    break
        points.append({
            "tenor_years": _clean(round(float(tenor), 4)),
            "yield_pct": _clean(round(float(y), 4)),
            "source": "observed" if is_observed else "interpolated",
        })

    as_of = max(latest_dates) if latest_dates else None
    shape = curve_shape(points)

    return {
        "as_of": as_of,
        "points": points,
        "method": "fred_cmt_cubic_spline" if len(observed) >= 4 else "fred_cmt_linear",
        "n_observed": len(observed),
        "n_interpolated": len(points) - len(observed),
        **shape,
    }


def _yield_at(points: list[dict], tenor_yrs: float) -> float | None:
    """Find the yield at a specific tenor; linear-interpolates between points."""
    if not points:
        return None
    sorted_pts = sorted(points, key=lambda p: p["tenor_years"])
    tenors = [p["tenor_years"] for p in sorted_pts]
    yields = [p["yield_pct"] for p in sorted_pts]
    if tenor_yrs < tenors[0] or tenor_yrs > tenors[-1]:
        return None
    return float(np.interp(tenor_yrs, tenors, yields))


def curve_shape(points: list[dict]) -> dict:
    """
    Standard curve summary metrics.

    level_5y           — anchor for the curve level. 5Y is the canonical
                          midpoint and reflects the medium-term rate path.
    slope_10y2y        — the recession indicator. Negative = inverted.
    slope_30y10y       — long-end slope. Negative = long-end inverted
                          (rare; signals deflation expectations).
    butterfly_2y5y10y  — curvature: 2 · y(5) - y(2) - y(10). Positive
                          when the belly is rich; negative = "humped" curve.
    """
    if not points:
        return {
            "level_5y": None, "slope_10y2y": None,
            "slope_30y10y": None, "butterfly_2y5y10y": None,
        }
    y2 = _yield_at(points, 2.0)
    y5 = _yield_at(points, 5.0)
    y10 = _yield_at(points, 10.0)
    y30 = _yield_at(points, 30.0)

    slope_10_2 = (y10 - y2) if (y10 is not None and y2 is not None) else None
    slope_30_10 = (y30 - y10) if (y30 is not None and y10 is not None) else None
    butterfly = (
        2 * y5 - y2 - y10
        if y2 is not None and y5 is not None and y10 is not None
        else None
    )
    return {
        "level_5y": _clean(round(y5, 4)) if y5 is not None else None,
        "slope_10y2y": _clean(round(slope_10_2, 4)) if slope_10_2 is not None else None,
        "slope_30y10y": _clean(round(slope_30_10, 4)) if slope_30_10 is not None else None,
        "butterfly_2y5y10y": _clean(round(butterfly, 4)) if butterfly is not None else None,
    }


def curve_regime(history_days: int = 120) -> dict:
    """
    Classify yield-curve evolution over the last `history_days` into one of:

      bull_steepener  — yields ↓, slope ↑   (short end rallies hardest;
                         typical near Fed easing cycle starts)
      bull_flattener  — yields ↓, slope ↓   (long end rallies hardest;
                         deflation / growth-scare signal)
      bear_steepener  — yields ↑, slope ↑   (long end sells off; inflation
                         / term-premium signal)
      bear_flattener  — yields ↑, slope ↓   (short end rises faster;
                         classic Fed hiking cycle)
      stable          — |Δlevel| < 25bp AND |Δslope| < 25bp

    Returns the deltas, classification, and the 2Y / 10Y endpoints used.
    """
    from data.fred_client import FREDDataClient
    fred = FREDDataClient()

    try:
        h2 = fred.get_series_history("DGS2", lookback_days=history_days + 30)
        h10 = fred.get_series_history("DGS10", lookback_days=history_days + 30)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"curve_regime FRED fetch failed: {e}")
        return {"regime": "unknown", "error": str(e)}

    if not h2 or not h10:
        return {"regime": "unknown", "error": "FRED returned no DGS2 / DGS10 data"}

    # Align on dates; keep only the last history_days worth
    map2 = {h["date"]: float(h["value"]) for h in h2 if h.get("value") is not None}
    map10 = {h["date"]: float(h["value"]) for h in h10 if h.get("value") is not None}
    common = sorted(set(map2.keys()) & set(map10.keys()))
    if len(common) < 30:
        return {
            "regime": "unknown",
            "error": f"Insufficient overlap (n={len(common)})",
        }

    common = common[-history_days:]
    y2 = np.array([map2[d] for d in common])
    y10 = np.array([map10[d] for d in common])

    # Winsorize for resilience to one-off bad prints
    y2 = _winsorize(y2)
    y10 = _winsorize(y10)
    slope = y10 - y2
    level = (y2 + y10) / 2.0

    delta_level_bp = float((level[-1] - level[0]) * 100)  # %-points → bps
    delta_slope_bp = float((slope[-1] - slope[0]) * 100)

    if abs(delta_level_bp) < REGIME_STABLE_BP and abs(delta_slope_bp) < REGIME_STABLE_BP:
        regime = "stable"
    elif delta_level_bp < 0 and delta_slope_bp > 0:
        regime = "bull_steepener"
    elif delta_level_bp < 0 and delta_slope_bp < 0:
        regime = "bull_flattener"
    elif delta_level_bp > 0 and delta_slope_bp > 0:
        regime = "bear_steepener"
    elif delta_level_bp > 0 and delta_slope_bp < 0:
        regime = "bear_flattener"
    else:
        regime = "stable"

    return {
        "regime": regime,
        "window_days": history_days,
        "first_date": common[0],
        "last_date": common[-1],
        "delta_level_bp": round(delta_level_bp, 1),
        "delta_slope_bp": round(delta_slope_bp, 1),
        "level_start_pct": round(float(level[0]), 3),
        "level_end_pct": round(float(level[-1]), 3),
        "slope_start_pct": round(float(slope[0]), 3),
        "slope_end_pct": round(float(slope[-1]), 3),
        "y2_end_pct": round(float(y2[-1]), 3),
        "y10_end_pct": round(float(y10[-1]), 3),
        "stable_threshold_bp": REGIME_STABLE_BP,
    }


def _fetch_yield_change_series(
    series_id: str, lookback_days: int
) -> dict[str, float]:
    """
    Returns a {date: daily_change_in_yield_pct} dict for a single FRED series.
    Daily change is computed as Δy_t = y_t - y_{t-1}.
    """
    from data.fred_client import FREDDataClient
    fred = FREDDataClient()
    try:
        hist = fred.get_series_history(series_id, lookback_days=lookback_days + 30)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"_fetch_yield_change_series {series_id}: {e}")
        return {}
    if not hist:
        return {}

    sorted_h = sorted(
        (h for h in hist if h.get("value") is not None),
        key=lambda h: h["date"],
    )
    if len(sorted_h) < 2:
        return {}
    out: dict[str, float] = {}
    for i in range(1, len(sorted_h)):
        prev_v = float(sorted_h[i - 1]["value"])
        cur_v = float(sorted_h[i]["value"])
        out[sorted_h[i]["date"]] = cur_v - prev_v
    return out


def _tenor_to_series_id(tenor_yrs: float) -> str | None:
    """Map a tenor in years to the canonical FRED CMT series ID."""
    mapping = {
        1 / 12: "DGS1MO", 0.25: "DGS3MO", 0.5: "DGS6MO",
        1.0: "DGS1", 2.0: "DGS2", 3.0: "DGS3",
        5.0: "DGS5", 7.0: "DGS7", 10.0: "DGS10",
        20.0: "DGS20", 30.0: "DGS30",
    }
    for k, v in mapping.items():
        if abs(k - tenor_yrs) < 1e-3:
            return v
    return None


def key_rate_durations(
    asset_returns: dict[str, list[dict]],
    lookback_days: int = 252,
    tenors: list[float] | None = None,
) -> dict:
    """
    Empirical key-rate sensitivities via joint OLS regression:

        r_i,t  =  α_i  +  Σ_k  β_i,k · Δy_k,t  +  ε_t

    For each asset i, returns β_i,k where k ∈ {2Y, 5Y, 10Y, 30Y} by default.

    Semantics:
      - For bond proxies (TLT, IEF, etc.) the magnitude approximates a
        key-rate duration; β_10y ≈ -7 for a 10Y bond fund means a 1pp
        rise in the 10Y yield drops the fund ~7%.
      - For equities, β_k is a "rate beta" — typically small and negative
        for growth/long-duration equities, near zero for value/financials,
        sometimes positive for short-duration cyclicals.

    asset_returns format: {ticker: [{"date": "YYYY-MM-DD", "close": float}, ...]}
        (matches the market_client.get_price_history output)

    Returns per-asset {betas, t_stats, r_squared, alpha_daily, n_observations}
    plus the key tenors used and a flag for any name that failed (insufficient
    data / collinearity).
    """
    if tenors is None:
        tenors = DEFAULT_KEY_RATE_TENORS

    # Fetch yield-change series for each requested tenor
    yield_changes: dict[float, dict[str, float]] = {}
    for tenor in tenors:
        series_id = _tenor_to_series_id(tenor)
        if not series_id:
            logger.warning(f"No FRED series mapped for tenor {tenor}y")
            continue
        yc = _fetch_yield_change_series(series_id, lookback_days)
        if not yc:
            logger.warning(f"Empty yield-change series for {series_id}")
            continue
        yield_changes[tenor] = yc

    if len(yield_changes) < 2:
        return {
            "error": "Insufficient yield-change tenors fetched",
            "tenors_used": list(yield_changes.keys()),
        }

    active_tenors = sorted(yield_changes.keys())
    results: dict[str, dict] = {}

    for ticker, history in asset_returns.items():
        if not history or len(history) < 30:
            results[ticker] = {"error": f"Insufficient price history (n={len(history) if history else 0})"}
            continue

        # Build a per-date dict of asset returns
        sorted_h = sorted(
            (h for h in history if h.get("close") is not None),
            key=lambda h: h["date"],
        )
        if len(sorted_h) < 30:
            results[ticker] = {"error": "Insufficient finite closes"}
            continue
        asset_ret: dict[str, float] = {}
        for i in range(1, len(sorted_h)):
            p_prev = float(sorted_h[i - 1]["close"])
            p_cur = float(sorted_h[i]["close"])
            if p_prev > 0:
                asset_ret[sorted_h[i]["date"]] = (p_cur - p_prev) / p_prev

        # Align on common dates across asset and all tenors
        date_sets = [set(asset_ret.keys())] + [set(yield_changes[t].keys()) for t in active_tenors]
        common = sorted(set.intersection(*date_sets))
        if len(common) < 60:
            results[ticker] = {
                "error": f"Insufficient aligned observations (n={len(common)})",
                "n_observations": len(common),
            }
            continue

        y_vec = np.array([asset_ret[d] for d in common], dtype=float)
        X_cols = []
        for tenor in active_tenors:
            col = np.array([yield_changes[tenor][d] for d in common], dtype=float)
            # Winsorize each tenor's daily changes to suppress data-error spikes
            col = _winsorize(col)
            X_cols.append(col)
        X = np.column_stack(X_cols)

        # Winsorize asset returns too
        y_vec = _winsorize(y_vec)

        # OLS via lstsq (with intercept)
        X_const = np.column_stack([np.ones(len(y_vec)), X])
        try:
            coefs, *_ = np.linalg.lstsq(X_const, y_vec, rcond=None)
        except np.linalg.LinAlgError as e:
            results[ticker] = {"error": f"OLS failed: {e}"}
            continue

        alpha_daily = float(coefs[0])
        betas = [float(c) for c in coefs[1:]]

        y_hat = X_const @ coefs
        resid = y_vec - y_hat
        ss_res = float(np.sum(resid ** 2))
        ss_tot = float(np.sum((y_vec - y_vec.mean()) ** 2))
        r_sq = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # t-stats via classic OLS variance formula
        n_obs = len(y_vec)
        n_params = X_const.shape[1]
        dof = max(1, n_obs - n_params)
        sigma_sq = ss_res / dof
        try:
            xtx_inv = np.linalg.inv(X_const.T @ X_const)
            se = np.sqrt(np.diag(xtx_inv) * sigma_sq)
            t_stats = [float(c / s) if s > 0 else None for c, s in zip(coefs, se)]
        except np.linalg.LinAlgError:
            t_stats = [None] * len(coefs)

        results[ticker] = {
            "betas": {
                f"{tenor:g}y": _clean(round(b, 4))
                for tenor, b in zip(active_tenors, betas)
            },
            "t_stats": {
                f"{tenor:g}y": _clean(round(t, 2)) if t is not None else None
                for tenor, t in zip(active_tenors, t_stats[1:])
            },
            "alpha_daily": _clean(round(alpha_daily, 6)),
            "alpha_annualized_pct": _clean(round(alpha_daily * 252 * 100, 2)),
            "alpha_tstat": _clean(round(t_stats[0], 2)) if t_stats[0] is not None else None,
            "r_squared": _clean(round(r_sq, 3)),
            "n_observations": int(n_obs),
        }

    return {
        "tenors_used": [f"{t:g}y" for t in active_tenors],
        "lookback_days": lookback_days,
        "results": results,
        "method": "joint_ols_winsorized",
    }
