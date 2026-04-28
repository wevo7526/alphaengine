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
