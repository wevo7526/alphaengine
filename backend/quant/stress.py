"""
Portfolio stress testing — historical scenarios and hypothetical shocks.

Two categories:

1. HISTORICAL SCENARIOS: replay actual market periods on the user's current
   book by applying observed sector returns to the user's positions. The
   number tells you "if 2008 happened again to your current portfolio, you
   would have lost X%."

2. HYPOTHETICAL SHOCKS: parameterized "what-if" scenarios — VIX +15,
   credit-spreads +200bp, oil +50%, USD +10%. These are linear shock
   models that translate the shock into per-sector return assumptions
   (calibrated from historical regressions, hardcoded here for speed).

Pure math, deterministic, fast. The risk dashboard exposes results so the
user can answer "how does this book look in a crisis?" — the question
every executive will ask.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# HISTORICAL SCENARIOS
# Sector returns during named historical periods. Sourced from S&P sector
# index returns over the cited windows. These are *peak-to-trough* returns
# during the named crisis — they overstate "stress" if the user opens a
# position mid-crisis, but for a forward-looking what-if they're correct.
# ============================================================================

HISTORICAL_SCENARIOS: dict[str, dict] = {
    "gfc_2008": {
        "label": "Global Financial Crisis (Sep 2008 - Mar 2009)",
        "window": "2008-09-01 to 2009-03-09",
        "spy_return_pct": -52.0,
        "vix_peak": 80.9,
        "sector_returns_pct": {
            "Technology": -45.0,
            "Communication Services": -42.0,
            "Consumer Cyclical": -54.0,
            "Consumer Defensive": -28.0,
            "Healthcare": -32.0,
            "Financial Services": -78.0,
            "Industrials": -56.0,
            "Energy": -50.0,
            "Utilities": -40.0,
            "Real Estate": -73.0,
            "Basic Materials": -55.0,
            "ETF/Broad": -52.0,
            "ETF/Bond": 8.0,    # treasuries rallied
            "ETF/Vol": 280.0,   # VIX products spiked
            "Unknown": -52.0,
        },
    },
    "covid_2020": {
        "label": "COVID Crash (Feb 19 - Mar 23 2020)",
        "window": "2020-02-19 to 2020-03-23",
        "spy_return_pct": -34.0,
        "vix_peak": 82.7,
        "sector_returns_pct": {
            "Technology": -28.0,
            "Communication Services": -27.0,
            "Consumer Cyclical": -33.0,
            "Consumer Defensive": -21.0,
            "Healthcare": -27.0,
            "Financial Services": -43.0,
            "Industrials": -39.0,
            "Energy": -56.0,
            "Utilities": -36.0,
            "Real Estate": -42.0,
            "Basic Materials": -36.0,
            "ETF/Broad": -34.0,
            "ETF/Bond": 6.0,
            "ETF/Vol": 260.0,
            "Unknown": -34.0,
        },
    },
    "rate_shock_2022": {
        "label": "2022 Rate Shock (Jan - Oct 2022)",
        "window": "2022-01-03 to 2022-10-12",
        "spy_return_pct": -25.0,
        "vix_peak": 36.5,
        "sector_returns_pct": {
            "Technology": -36.0,
            "Communication Services": -42.0,
            "Consumer Cyclical": -34.0,
            "Consumer Defensive": -7.0,
            "Healthcare": -10.0,
            "Financial Services": -19.0,
            "Industrials": -19.0,
            "Energy": +44.0,    # oil rallied
            "Utilities": -10.0,
            "Real Estate": -32.0,
            "Basic Materials": -20.0,
            "ETF/Broad": -25.0,
            "ETF/Bond": -18.0,  # bonds got hammered too
            "ETF/Vol": 45.0,
            "Unknown": -25.0,
        },
    },
    "dotcom_2000": {
        "label": "Dot-Com Bust (Mar 2000 - Oct 2002)",
        "window": "2000-03-24 to 2002-10-09",
        "spy_return_pct": -49.0,
        "vix_peak": 45.7,
        "sector_returns_pct": {
            "Technology": -82.0,
            "Communication Services": -67.0,
            "Consumer Cyclical": -41.0,
            "Consumer Defensive": +5.0,
            "Healthcare": -7.0,
            "Financial Services": -25.0,
            "Industrials": -29.0,
            "Energy": -15.0,
            "Utilities": -26.0,
            "Real Estate": +18.0,
            "Basic Materials": -13.0,
            "ETF/Broad": -49.0,
            "ETF/Bond": 25.0,
            "ETF/Vol": 100.0,
            "Unknown": -49.0,
        },
    },
}


# ============================================================================
# HYPOTHETICAL SHOCKS
# Linear sensitivity models: shock_param -> per-sector return.
# Coefficients are approximate betas calibrated from rolling regressions of
# sector returns against the shock variable over 2008-2024. Hardcoded for
# determinism; can be re-fit periodically.
# ============================================================================

# Beta of sector daily return to a 1-point VIX move.
# Negative = goes down when VIX spikes (typical equity behavior).
VIX_SECTOR_BETAS: dict[str, float] = {
    "Technology": -0.0040,
    "Communication Services": -0.0038,
    "Consumer Cyclical": -0.0042,
    "Consumer Defensive": -0.0020,
    "Healthcare": -0.0025,
    "Financial Services": -0.0048,
    "Industrials": -0.0040,
    "Energy": -0.0035,
    "Utilities": -0.0018,
    "Real Estate": -0.0038,
    "Basic Materials": -0.0040,
    "ETF/Broad": -0.0036,
    "ETF/Bond": +0.0010,
    "ETF/Vol": +0.0420,    # VIX products explode
    "Unknown": -0.0036,
}

# Beta of sector daily return to a 1bp move in HY credit spreads.
# Wider spreads = stress = equities down.
CREDIT_SECTOR_BETAS: dict[str, float] = {
    "Technology": -0.00018,
    "Communication Services": -0.00016,
    "Consumer Cyclical": -0.00025,
    "Consumer Defensive": -0.00008,
    "Healthcare": -0.00010,
    "Financial Services": -0.00038,
    "Industrials": -0.00022,
    "Energy": -0.00026,
    "Utilities": -0.00006,
    "Real Estate": -0.00028,
    "Basic Materials": -0.00022,
    "ETF/Broad": -0.00018,
    "ETF/Bond": -0.00012,
    "ETF/Vol": +0.00150,
    "Unknown": -0.00018,
}

# Beta of sector daily return to a 1% move in WTI crude.
# Positive for energy, slightly negative for consumer-facing sectors.
OIL_SECTOR_BETAS: dict[str, float] = {
    "Technology": -0.0008,
    "Communication Services": -0.0006,
    "Consumer Cyclical": -0.0015,
    "Consumer Defensive": -0.0005,
    "Healthcare": -0.0002,
    "Financial Services": -0.0004,
    "Industrials": +0.0008,
    "Energy": +0.0085,
    "Utilities": -0.0006,
    "Real Estate": -0.0004,
    "Basic Materials": +0.0040,
    "ETF/Broad": -0.0002,
    "ETF/Bond": -0.0008,
    "ETF/Vol": +0.0010,
    "Unknown": -0.0002,
}


def historical_scenario(
    scenario_key: str,
    positions: list[dict],
    portfolio_base: float = 100000,
) -> dict:
    """
    Apply a named historical scenario to the user's current positions.

    `positions` is a list of dicts with at minimum:
        {ticker, sector, size_pct, direction}

    Returns the implied portfolio P&L as percent and dollars, plus the
    per-position breakdown so the dashboard can show "your AAPL position
    would have lost 28% in COVID".
    """
    scenario = HISTORICAL_SCENARIOS.get(scenario_key)
    if not scenario:
        return {"error": f"Unknown scenario '{scenario_key}'"}

    sector_rets = scenario["sector_returns_pct"]
    pnl_pct = 0.0
    breakdown: list[dict] = []

    for p in positions:
        sector = p.get("sector") or "Unknown"
        sector_ret = sector_rets.get(sector, sector_rets.get("Unknown", 0.0))
        size = float(p.get("size_pct", 0)) / 100.0
        is_long = "bullish" in (p.get("direction") or "")
        signed_ret = sector_ret if is_long else -sector_ret
        contribution = signed_ret * size
        pnl_pct += contribution
        breakdown.append({
            "ticker": p.get("ticker"),
            "sector": sector,
            "size_pct": p.get("size_pct"),
            "direction": p.get("direction"),
            "scenario_sector_return_pct": round(sector_ret, 2),
            "position_pnl_pct": round(contribution, 3),
        })

    return {
        "scenario": scenario_key,
        "label": scenario["label"],
        "window": scenario["window"],
        "spy_return_pct": scenario["spy_return_pct"],
        "vix_peak": scenario["vix_peak"],
        "portfolio_pnl_pct": round(pnl_pct, 3),
        "portfolio_pnl_dollars": round(pnl_pct / 100.0 * portfolio_base, 2),
        "breakdown": breakdown,
    }


def hypothetical_shock(
    shock: dict,
    positions: list[dict],
    portfolio_base: float = 100000,
) -> dict:
    """
    Apply a parameterized hypothetical shock. Supported shock types:

        {"type": "vix_spike",     "delta": 15}    # VIX +15 points
        {"type": "credit_widen",  "delta_bps": 200}  # spreads +200bp
        {"type": "oil_shock",     "delta_pct": 50}   # WTI +50%
        {"type": "combined", "components": [<shock>, <shock>, ...]}

    Linearity: portfolio impact = sum over positions of (sector_beta * shock_size *
    position_weight * direction_sign). Fast and transparent — the risk desk
    can sanity-check every number by hand.
    """
    if shock.get("type") == "combined":
        components = shock.get("components", [])
        total_pnl_pct = 0.0
        sub_results = []
        for comp in components:
            sub = hypothetical_shock(comp, positions, portfolio_base)
            sub_results.append(sub)
            total_pnl_pct += sub.get("portfolio_pnl_pct", 0.0)
        return {
            "shock": shock,
            "portfolio_pnl_pct": round(total_pnl_pct, 3),
            "portfolio_pnl_dollars": round(total_pnl_pct / 100.0 * portfolio_base, 2),
            "components": sub_results,
        }

    shock_type = shock.get("type")
    if shock_type == "vix_spike":
        beta_map = VIX_SECTOR_BETAS
        size = float(shock.get("delta", 0))
        unit = "VIX points"
    elif shock_type == "credit_widen":
        beta_map = CREDIT_SECTOR_BETAS
        size = float(shock.get("delta_bps", 0))
        unit = "bp"
    elif shock_type == "oil_shock":
        beta_map = OIL_SECTOR_BETAS
        size = float(shock.get("delta_pct", 0))
        unit = "% (WTI)"
    else:
        return {"error": f"Unknown shock type '{shock_type}'"}

    pnl_pct = 0.0
    breakdown: list[dict] = []
    for p in positions:
        sector = p.get("sector") or "Unknown"
        beta = beta_map.get(sector, beta_map.get("Unknown", 0.0))
        position_ret = beta * size  # decimal return
        weight = float(p.get("size_pct", 0)) / 100.0
        is_long = "bullish" in (p.get("direction") or "")
        signed = position_ret if is_long else -position_ret
        contribution = signed * weight * 100.0  # convert to %
        pnl_pct += contribution
        breakdown.append({
            "ticker": p.get("ticker"),
            "sector": sector,
            "size_pct": p.get("size_pct"),
            "direction": p.get("direction"),
            "implied_position_return_pct": round(position_ret * 100, 3),
            "position_pnl_pct": round(contribution, 3),
        })

    return {
        "shock": {"type": shock_type, "size": size, "unit": unit},
        "portfolio_pnl_pct": round(pnl_pct, 3),
        "portfolio_pnl_dollars": round(pnl_pct / 100.0 * portfolio_base, 2),
        "breakdown": breakdown,
    }


# ============================================================================
# CUSTOM EMPIRICAL SCENARIO (Phase C: cross-asset reach)
#
# Per-position betas to rates / credit / commodity / FX / vol shocks are
# fit at request time from 1y daily history via OLS on cross-asset proxy
# returns — NO hardcoded sector lookups for these axes. This is the
# "what if oil +30%, rates +100bp" engine PMs actually use.
# ============================================================================

# Cross-asset proxy ETFs. We use TLT (long-duration Treasury) for rates
# because its modified duration is ~17y, giving the cleanest empirical
# signal in regression. UUP (USD index ETF) is the FX proxy.
CROSS_ASSET_PROXIES: dict[str, str] = {
    "rates": "TLT",        # 20+y Treasury — moves -duration × Δyield
    "credit": "HYG",       # high-yield credit — sensitive to spread changes
    "oil": "USO",          # WTI crude oil
    "gold": "GLD",         # gold (alt safe-haven asset)
    "fx": "UUP",           # USD index
    "vol": "VXX",          # VIX futures ETF (already covered by VIX shock)
}

# TLT effective duration: -Δprice / Δyield ≈ 17.5y. Standard published value.
# Used only as a fallback when the empirical TLT-vs-FRED-yield regression
# can't run (FRED unreachable). Real PMs reach for this number in their
# heads to translate basis-point shocks to expected TLT P&L.
TLT_EFFECTIVE_DURATION_YEARS = 17.5

# Conventional bp→pct mapping for credit. HYG has effective duration ~4y
# but credit spread moves matter more than rate moves; empirical 1bp move
# in HY spreads correlates to ~-0.04% HYG return historically.
# Used only as fallback.
HYG_BP_TO_PCT_FALLBACK = -0.0004


def _fit_position_shock_betas(
    position_returns: dict[str, list[float]],
    proxy_returns: dict[str, list[float]],
) -> dict[str, dict[str, float | None]]:
    """
    For each position ticker, run OLS of its daily returns on each cross-
    asset proxy's daily returns. Each regression is univariate — multivariate
    on highly correlated proxies (TLT/HYG/GLD) blows up the coefficients
    via multicollinearity. The univariate β captures the marginal
    sensitivity, which is what a scenario shock should multiply.

    Returns:
      {ticker: {rates: β_TLT or None, credit: β_HYG or None,
                oil: β_USO or None, gold: β_GLD or None,
                fx: β_UUP or None, n_obs: int}}
    """
    import numpy as np

    out: dict[str, dict[str, float | None]] = {}
    for ticker, pos_rets in position_returns.items():
        out[ticker] = {"rates": None, "credit": None, "oil": None, "gold": None, "fx": None, "n_obs": 0}
        if not pos_rets or len(pos_rets) < 30:
            continue
        y_full = np.array(pos_rets, dtype=float)
        for axis, proxy_ticker in [
            ("rates", "TLT"), ("credit", "HYG"), ("oil", "USO"),
            ("gold", "GLD"), ("fx", "UUP"),
        ]:
            proxy_rets = proxy_returns.get(proxy_ticker)
            if not proxy_rets or len(proxy_rets) < 30:
                continue
            min_len = min(len(y_full), len(proxy_rets))
            if min_len < 30:
                continue
            y = y_full[-min_len:]
            x = np.array(proxy_rets[-min_len:], dtype=float)
            x_var = float(np.var(x, ddof=1))
            if x_var < 1e-12:
                continue
            # Univariate OLS slope = cov(y, x) / var(x)
            beta = float(np.cov(y, x, ddof=1)[0, 1] / x_var)
            if math.isfinite(beta):
                out[ticker][axis] = round(beta, 4)
            out[ticker]["n_obs"] = int(min_len)
    return out


def custom_macro_scenario(
    positions: list[dict],
    shock: dict,
    portfolio_base: float = 100000,
    history_period: str = "1y",
) -> dict:
    """
    Apply a custom cross-asset shock to a book using empirical per-position
    betas, fit fresh from 1y daily history.

    `shock` accepts:
      - rates_shock_bps      (int/float)  — bp move in 10y yield; positive = rates UP
      - credit_shock_bps     (int/float)  — bp widening in HY OAS
      - oil_shock_pct        (float)      — % change in WTI/USO
      - gold_shock_pct       (float)      — % change in GLD
      - fx_shock_pct         (float)      — % change in DXY/UUP (positive = USD up)

    Per-position projected return =
        β_TLT × (-TLT_duration × rates_bps/10000)   # rates leg
      + β_HYG × (HYG_bp_fallback × credit_bps)      # credit leg
      + β_USO × (oil_shock_pct/100)                 # oil leg
      + β_GLD × (gold_shock_pct/100)                # gold leg
      + β_UUP × (fx_shock_pct/100)                  # fx leg

    Then position contribution = projected_return × weight × direction_sign.

    Empirical betas come from OLS univariate regression on 1y daily returns
    of each proxy ETF — no hardcoded sector tables on this path. Returns
    per-position breakdown with β values + projected return for full PM
    auditability.
    """
    if not isinstance(shock, dict):
        return {"error": "shock must be a dict"}

    # Extract shock parameters; treat missing as 0
    def _num(key: str) -> float:
        v = shock.get(key)
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    rates_bps = _num("rates_shock_bps")
    credit_bps = _num("credit_shock_bps")
    oil_pct = _num("oil_shock_pct")
    gold_pct = _num("gold_shock_pct")
    fx_pct = _num("fx_shock_pct")

    if not (rates_bps or credit_bps or oil_pct or gold_pct or fx_pct):
        return {"error": "All shock params are zero — nothing to compute"}

    # Map bp shocks to expected proxy ETF returns
    expected_tlt_return = -TLT_EFFECTIVE_DURATION_YEARS * rates_bps / 10000.0
    expected_hyg_return = HYG_BP_TO_PCT_FALLBACK * credit_bps
    expected_uso_return = oil_pct / 100.0
    expected_gld_return = gold_pct / 100.0
    expected_uup_return = fx_pct / 100.0

    tickers = [(p.get("ticker") or "").upper() for p in positions]
    tickers = [t for t in tickers if t]
    if not tickers:
        return {"error": "No positions provided"}

    from data.market_client import MarketDataClient
    market = MarketDataClient()

    # Build daily return series for each position + each proxy ETF
    def _to_returns(history: list[dict]) -> list[float]:
        rets: list[float] = []
        prev = None
        for bar in history or []:
            c = bar.get("close")
            if c is None or c <= 0:
                continue
            if prev is not None and prev > 0:
                rets.append((c - prev) / prev)
            prev = c
        return rets

    position_returns: dict[str, list[float]] = {}
    for t in tickers:
        try:
            history = market.get_price_history(t, period=history_period)
        except Exception as e:
            logger.debug(f"custom_scenario: history fetch for {t} failed: {e}")
            continue
        if history:
            position_returns[t] = _to_returns(history)

    proxy_returns: dict[str, list[float]] = {}
    for _, proxy_ticker in CROSS_ASSET_PROXIES.items():
        try:
            history = market.get_price_history(proxy_ticker, period=history_period)
        except Exception as e:
            logger.debug(f"custom_scenario: history fetch for proxy {proxy_ticker} failed: {e}")
            continue
        if history:
            proxy_returns[proxy_ticker] = _to_returns(history)

    betas = _fit_position_shock_betas(position_returns, proxy_returns)

    portfolio_pnl_pct = 0.0
    breakdown: list[dict] = []
    for p in positions:
        ticker = (p.get("ticker") or "").upper()
        if not ticker:
            continue
        b = betas.get(ticker) or {}
        weight = float(p.get("size_pct", 0) or 0) / 100.0
        is_long = "bullish" in (p.get("direction") or "")
        sign = 1.0 if is_long else -1.0

        projected_return = 0.0
        contributions: dict[str, float] = {}

        if rates_bps and b.get("rates") is not None:
            r = float(b["rates"]) * expected_tlt_return
            contributions["rates"] = round(r, 5)
            projected_return += r
        if credit_bps and b.get("credit") is not None:
            r = float(b["credit"]) * expected_hyg_return
            contributions["credit"] = round(r, 5)
            projected_return += r
        if oil_pct and b.get("oil") is not None:
            r = float(b["oil"]) * expected_uso_return
            contributions["oil"] = round(r, 5)
            projected_return += r
        if gold_pct and b.get("gold") is not None:
            r = float(b["gold"]) * expected_gld_return
            contributions["gold"] = round(r, 5)
            projected_return += r
        if fx_pct and b.get("fx") is not None:
            r = float(b["fx"]) * expected_uup_return
            contributions["fx"] = round(r, 5)
            projected_return += r

        position_pnl_pct = projected_return * weight * sign * 100.0
        portfolio_pnl_pct += position_pnl_pct

        breakdown.append({
            "ticker": ticker,
            "weight_pct": p.get("size_pct"),
            "direction": p.get("direction"),
            "betas": {k: b.get(k) for k in ("rates", "credit", "oil", "gold", "fx")},
            "n_obs": b.get("n_obs", 0),
            "contributions_by_axis": contributions,
            "projected_position_return_pct": round(projected_return * 100.0, 3),
            "position_pnl_pct": round(position_pnl_pct, 3),
        })

    return {
        "shock_inputs": {
            "rates_shock_bps": rates_bps,
            "credit_shock_bps": credit_bps,
            "oil_shock_pct": oil_pct,
            "gold_shock_pct": gold_pct,
            "fx_shock_pct": fx_pct,
        },
        "expected_proxy_returns": {
            "TLT_pct": round(expected_tlt_return * 100, 3),
            "HYG_pct": round(expected_hyg_return * 100, 3),
            "USO_pct": round(expected_uso_return * 100, 3),
            "GLD_pct": round(expected_gld_return * 100, 3),
            "UUP_pct": round(expected_uup_return * 100, 3),
        },
        "portfolio_pnl_pct": round(portfolio_pnl_pct, 3),
        "portfolio_pnl_dollars": round(portfolio_pnl_pct / 100.0 * portfolio_base, 2),
        "breakdown": breakdown,
        "beta_method": "univariate_ols_1y_daily_returns",
        "history_period": history_period,
        "n_positions": len(breakdown),
    }


def run_full_stress_panel(positions: list[dict], portfolio_base: float = 100000) -> dict:
    """
    Run the full stress panel: every historical scenario + the standard
    hypothetical shocks. This is what the risk dashboard calls.
    """
    historical = {
        key: historical_scenario(key, positions, portfolio_base)
        for key in HISTORICAL_SCENARIOS
    }

    standard_shocks: list[dict[str, Any]] = [
        {"type": "vix_spike", "delta": 15},
        {"type": "vix_spike", "delta": 30},
        {"type": "credit_widen", "delta_bps": 200},
        {"type": "credit_widen", "delta_bps": 500},
        {"type": "oil_shock", "delta_pct": 50},
        {"type": "oil_shock", "delta_pct": -30},
        {
            "type": "combined",
            "label": "Risk-off cocktail",
            "components": [
                {"type": "vix_spike", "delta": 20},
                {"type": "credit_widen", "delta_bps": 300},
                {"type": "oil_shock", "delta_pct": -25},
            ],
        },
    ]

    hypothetical = [
        hypothetical_shock(s, positions, portfolio_base) for s in standard_shocks
    ]

    return {
        "portfolio_base": portfolio_base,
        "position_count": len(positions),
        "historical": historical,
        "hypothetical": hypothetical,
    }
