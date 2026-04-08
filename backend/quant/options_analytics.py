"""
Options analytics module — pure math, no LLM.

Black-Scholes-Merton pricing, Greeks, unusual activity detection,
implied move computation. All computed from live options chain data.
"""

import numpy as np
from scipy.stats import norm
import logging

from data.market_client import MarketDataClient

logger = logging.getLogger(__name__)

_market = MarketDataClient()


# === Black-Scholes-Merton ===

def black_scholes(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
    """BSM option price. S=spot, K=strike, T=years to expiry, r=risk-free rate, sigma=IV."""
    if T <= 0 or sigma <= 0:
        return max(0, S - K) if option_type == "call" else max(0, K - S)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == "call":
        return float(S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))
    else:
        return float(K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))


def calculate_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> dict:
    """Compute delta, gamma, theta, vega for an option."""
    if T <= 0 or sigma <= 0:
        return {"delta": 1.0 if option_type == "call" else -1.0, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)

    delta = float(norm.cdf(d1)) if option_type == "call" else float(norm.cdf(d1) - 1)
    gamma = float(norm.pdf(d1) / (S * sigma * np.sqrt(T)))
    theta_call = float(
        -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
        - r * K * np.exp(-r * T) * norm.cdf(d2)
    ) / 365
    theta_put = float(
        -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))
        + r * K * np.exp(-r * T) * norm.cdf(-d2)
    ) / 365
    theta = theta_call if option_type == "call" else theta_put
    vega = float(S * norm.pdf(d1) * np.sqrt(T)) / 100

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
    }


# === Options Chain Analysis ===

def analyze_options(ticker: str) -> dict:
    """
    Full options analysis for a ticker. Returns:
    - put_call_ratio: aggregate volume ratio
    - implied_move_pct: ATM straddle implied move as % of stock price
    - iv_rank: current IV vs recent range (approximation)
    - unusual_activity: strikes with volume/OI > 2x
    - greeks_summary: ATM option Greeks
    - max_pain: strike with most OI concentration
    """
    fundamentals = _market.get_fundamentals(ticker)
    current_price = fundamentals.get("current_price")
    if not current_price:
        return {"ticker": ticker, "error": "No price data available"}

    chain = _market.get_options_chain(ticker)
    if not chain or not chain.get("calls") or not chain.get("puts"):
        return {"ticker": ticker, "error": "No options chain available"}

    calls = chain["calls"]
    puts = chain["puts"]
    expiration = chain.get("expiration", "unknown")

    # Put/Call ratio (volume-based)
    total_call_vol = sum(c.get("volume", 0) or 0 for c in calls)
    total_put_vol = sum(p.get("volume", 0) or 0 for p in puts)
    pc_ratio = round(total_put_vol / total_call_vol, 3) if total_call_vol > 0 else 0

    # Find ATM strike (closest to current price)
    all_strikes = [c.get("strike", 0) for c in calls]
    if not all_strikes:
        return {"ticker": ticker, "error": "No strikes in chain"}
    atm_strike = min(all_strikes, key=lambda x: abs(x - current_price))

    atm_call = next((c for c in calls if c.get("strike") == atm_strike), None)
    atm_put = next((p for p in puts if p.get("strike") == atm_strike), None)

    # Implied move from ATM straddle
    atm_call_price = atm_call.get("lastPrice", 0) if atm_call else 0
    atm_put_price = atm_put.get("lastPrice", 0) if atm_put else 0
    straddle_price = atm_call_price + atm_put_price
    implied_move_pct = round((straddle_price / current_price) * 100, 2) if current_price > 0 else 0

    # ATM IV
    atm_iv = atm_call.get("impliedVolatility", 0) if atm_call else 0

    # Greeks for ATM call
    T = 30 / 365  # Approximate days to expiry
    r = 0.0364  # Fed funds rate approximation
    greeks = calculate_greeks(current_price, atm_strike, T, r, atm_iv, "call") if atm_iv > 0 else {}

    # Unusual activity detection (volume/OI > 2x)
    unusual = []
    for opt_list, opt_type in [(calls, "call"), (puts, "put")]:
        for opt in opt_list:
            vol = opt.get("volume", 0) or 0
            oi = opt.get("openInterest", 0) or 0
            if oi > 0 and vol > 0:
                ratio = vol / oi
                if ratio > 2.0:
                    unusual.append({
                        "type": opt_type,
                        "strike": opt.get("strike"),
                        "volume": vol,
                        "open_interest": oi,
                        "vol_oi_ratio": round(ratio, 1),
                        "iv": round(opt.get("impliedVolatility", 0) * 100, 1),
                    })
    unusual.sort(key=lambda x: x["vol_oi_ratio"], reverse=True)

    # Max pain (strike with highest total OI)
    oi_by_strike = {}
    for c in calls:
        s = c.get("strike", 0)
        oi_by_strike[s] = oi_by_strike.get(s, 0) + (c.get("openInterest", 0) or 0)
    for p in puts:
        s = p.get("strike", 0)
        oi_by_strike[s] = oi_by_strike.get(s, 0) + (p.get("openInterest", 0) or 0)
    max_pain_strike = max(oi_by_strike, key=oi_by_strike.get) if oi_by_strike else atm_strike

    # IV skew: put IV vs call IV at ATM
    call_iv = atm_call.get("impliedVolatility", 0) if atm_call else 0
    put_iv = atm_put.get("impliedVolatility", 0) if atm_put else 0
    iv_skew = round((put_iv - call_iv) * 100, 2) if call_iv > 0 else 0

    return {
        "ticker": ticker,
        "current_price": current_price,
        "expiration": expiration,
        "put_call_ratio": pc_ratio,
        "implied_move_pct": implied_move_pct,
        "straddle_price": round(straddle_price, 2),
        "atm_strike": atm_strike,
        "atm_iv": round(atm_iv * 100, 1),
        "iv_skew": iv_skew,
        "max_pain": max_pain_strike,
        "greeks": greeks,
        "unusual_activity": unusual[:5],
        "total_call_volume": total_call_vol,
        "total_put_volume": total_put_vol,
        "pc_ratio_signal": "bearish" if pc_ratio > 1.5 else "bullish" if pc_ratio < 0.5 else "neutral",
    }
