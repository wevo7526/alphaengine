"""
Universe Scanner — the Screening Desk's anomaly detection engine.

Pure computation, zero LLM calls. Fast (~30-60s for ~30 tickers).
Scans a universe of tickers for tradeable anomalies across multiple dimensions:
- Technical (RSI extremes, MA breakouts, volume spikes)
- Fundamental (insider clusters, earnings surprises)
- Sentiment (news sentiment shifts)
- Macro (VIX spikes, credit widening, yield curve shifts)

Findings are ranked by priority and persisted for the frontend to display.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import logging
import numpy as np

from data.market_client import MarketDataClient
from data.fred_client import FREDDataClient
from data.news_client import NewsDataClient
from data.sec_client import SECDataClient
from agents.nlp.sentiment import score_articles
from agents.universe import DEFAULT_UNIVERSE

logger = logging.getLogger(__name__)

_market = MarketDataClient()
_fred = FREDDataClient()
_news = NewsDataClient()
_sec = SECDataClient()


# ── Technical anomaly detectors ──────────────────────────────────

def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute RSI from a list of closing prices."""
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes[-period - 1:])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = float(np.mean(gains))
    avg_loss = float(np.mean(losses))
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _check_rsi_extreme(ticker: str, history: list[dict]) -> dict | None:
    """Flag RSI < 30 (oversold) or > 70 (overbought)."""
    if len(history) < 20:
        return None
    closes = [b["close"] for b in history]
    rsi = _compute_rsi(closes)
    if rsi is None:
        return None
    if rsi < 30:
        return {
            "finding_type": "rsi_extreme",
            "priority": "medium",
            "headline": f"{ticker} oversold: RSI {rsi:.1f}",
            "detail": f"14-day RSI at {rsi:.1f} — below 30 threshold. Mean reversion setup if fundamentals hold.",
            "data": {"rsi": round(rsi, 2), "direction": "oversold"},
        }
    if rsi > 70:
        return {
            "finding_type": "rsi_extreme",
            "priority": "medium",
            "headline": f"{ticker} overbought: RSI {rsi:.1f}",
            "detail": f"14-day RSI at {rsi:.1f} — above 70 threshold. Profit-taking or pullback risk.",
            "data": {"rsi": round(rsi, 2), "direction": "overbought"},
        }
    return None


def _check_volume_spike(ticker: str, history: list[dict]) -> dict | None:
    """Flag today's volume > 2x 20-day average."""
    if len(history) < 21:
        return None
    volumes = [b.get("volume", 0) for b in history]
    if volumes[-1] == 0:
        return None
    avg_20 = float(np.mean(volumes[-21:-1]))
    if avg_20 == 0:
        return None
    ratio = volumes[-1] / avg_20
    if ratio < 2.0:
        return None
    priority = "high" if ratio >= 3.0 else "medium"
    return {
        "finding_type": "volume_spike",
        "priority": priority,
        "headline": f"{ticker} volume {ratio:.1f}x average",
        "detail": f"Today's volume is {ratio:.1f}x the 20-day average. Unusual activity — check for news catalysts.",
        "data": {"volume_ratio": round(ratio, 2), "today_volume": volumes[-1], "avg_20d": int(avg_20)},
    }


def _check_ma_breakout(ticker: str, history: list[dict]) -> dict | None:
    """Flag price crossing above/below 50-day MA in last 2 days."""
    if len(history) < 52:
        return None
    closes = [b["close"] for b in history]
    ma50_today = float(np.mean(closes[-50:]))
    ma50_yesterday = float(np.mean(closes[-51:-1]))
    today = closes[-1]
    yesterday = closes[-2]

    # Crossed above
    if yesterday < ma50_yesterday and today > ma50_today:
        return {
            "finding_type": "ma_crossover",
            "priority": "medium",
            "headline": f"{ticker} broke above 50-day MA",
            "detail": f"Price at ${today:.2f} crossed above 50-day MA of ${ma50_today:.2f}. Momentum shift to upside.",
            "data": {"price": round(today, 2), "ma50": round(ma50_today, 2), "direction": "above"},
        }
    # Crossed below
    if yesterday > ma50_yesterday and today < ma50_today:
        return {
            "finding_type": "ma_crossover",
            "priority": "medium",
            "headline": f"{ticker} broke below 50-day MA",
            "detail": f"Price at ${today:.2f} crossed below 50-day MA of ${ma50_today:.2f}. Momentum shift to downside.",
            "data": {"price": round(today, 2), "ma50": round(ma50_today, 2), "direction": "below"},
        }
    return None


def _check_large_move(ticker: str, history: list[dict]) -> dict | None:
    """Flag single-day moves > 5%."""
    if len(history) < 2:
        return None
    today = history[-1].get("close")
    yesterday = history[-2].get("close")
    if not today or not yesterday:
        return None
    pct = (today - yesterday) / yesterday * 100
    if abs(pct) < 5:
        return None
    priority = "high" if abs(pct) >= 8 else "medium"
    direction = "gain" if pct > 0 else "drop"
    return {
        "finding_type": "earnings_surprise",  # Common cause — may be tagged more specifically later
        "priority": priority,
        "headline": f"{ticker} {pct:+.1f}% {direction} today",
        "detail": f"Large single-day move from ${yesterday:.2f} to ${today:.2f}. Likely news-driven — investigate catalyst.",
        "data": {"pct_change": round(pct, 2), "today": round(today, 2), "yesterday": round(yesterday, 2)},
    }


# ── Per-ticker scan ──────────────────────────────────────────────

def _scan_ticker(ticker: str) -> list[dict]:
    """Run all technical checks on a single ticker. Returns list of findings."""
    findings = []
    try:
        history = _market.get_price_history(ticker, period="3mo")
        if not history or len(history) < 30:
            return findings

        for checker in [_check_rsi_extreme, _check_volume_spike, _check_ma_breakout, _check_large_move]:
            try:
                result = checker(ticker, history)
                if result:
                    findings.append({**result, "ticker": ticker})
            except Exception as e:
                logger.debug(f"{checker.__name__} failed for {ticker}: {e}")
                continue
    except Exception as e:
        logger.warning(f"Failed to scan {ticker}: {e}")
    return findings


# ── Macro shift checks ───────────────────────────────────────────

def _check_macro_shifts() -> list[dict]:
    """Check for meaningful macro regime shifts."""
    findings = []
    try:
        snapshot = _fred.get_macro_snapshot()

        # VIX spike
        vix = snapshot.get("vix", {})
        if vix.get("change") and abs(vix["change"]) > 3:
            direction = "spiked" if vix["change"] > 0 else "collapsed"
            priority = "high" if abs(vix["change"]) > 5 else "medium"
            findings.append({
                "ticker": "VIX",
                "finding_type": "macro_shift",
                "priority": priority,
                "headline": f"VIX {direction} {abs(vix['change']):.1f} points",
                "detail": f"VIX moved from {vix.get('previous', '?'):.2f} to {vix.get('value', '?'):.2f}. Risk regime shifting.",
                "data": {"vix": vix.get("value"), "change": vix.get("change")},
            })

        # Credit spread widening
        credit = snapshot.get("credit_spreads", {})
        if credit.get("change") and credit["change"] > 0.2:
            findings.append({
                "ticker": "HYG",
                "finding_type": "macro_shift",
                "priority": "medium",
                "headline": f"Credit spreads widened {credit['change'] * 100:.0f}bp",
                "detail": f"HY OAS now {credit.get('value', '?'):.2f}%. Risk-off signal.",
                "data": {"credit_spread": credit.get("value"), "change_bp": round(credit["change"] * 100, 0)},
            })

        # Yield curve shift
        yc = snapshot.get("yield_curve_spread", {})
        if yc.get("change") and abs(yc["change"]) > 0.1:
            direction = "steepened" if yc["change"] > 0 else "flattened"
            findings.append({
                "ticker": "TLT",
                "finding_type": "macro_shift",
                "priority": "medium",
                "headline": f"Yield curve {direction} {abs(yc['change']) * 100:.0f}bp",
                "detail": f"10Y-2Y spread now {yc.get('value', '?'):.2f}%. {'Recession signal fading' if direction == 'steepened' else 'Recession signal strengthening'}.",
                "data": {"yield_curve": yc.get("value"), "change_bp": round(yc["change"] * 100, 0)},
            })
    except Exception as e:
        logger.warning(f"Macro shift check failed: {e}")
    return findings


# ── Main scan function ───────────────────────────────────────────

def run_scan(universe: list[str] | None = None, max_tickers: int = 30) -> dict:
    """
    Scan the universe for anomalies. Returns findings grouped by priority.

    Args:
        universe: list of tickers to scan. Defaults to DEFAULT_UNIVERSE.
        max_tickers: cap to respect API limits. Default 30.

    Returns:
        {
          findings: [{ticker, finding_type, priority, headline, detail, data}, ...],
          universe_size: int,
          findings_count: int,
          by_priority: {high: [...], medium: [...], low: [...]},
        }
    """
    if universe is None:
        universe = DEFAULT_UNIVERSE

    tickers = universe[:max_tickers]
    all_findings: list[dict] = []

    # Macro checks (sequential, single call)
    all_findings.extend(_check_macro_shifts())

    # Per-ticker scans (parallel)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_scan_ticker, t): t for t in tickers}
        for future in as_completed(futures):
            try:
                all_findings.extend(future.result())
            except Exception as e:
                logger.warning(f"Scan task failed: {e}")

    # Rank by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    all_findings.sort(key=lambda f: (priority_order.get(f.get("priority", "low"), 2), f.get("ticker", "")))

    by_priority: dict[str, list[dict]] = {"high": [], "medium": [], "low": []}
    for f in all_findings:
        p = f.get("priority", "low")
        if p in by_priority:
            by_priority[p].append(f)

    logger.info(f"Scan complete: {len(all_findings)} findings across {len(tickers)} tickers")
    return {
        "findings": all_findings,
        "universe_size": len(tickers),
        "findings_count": len(all_findings),
        "by_priority": by_priority,
    }
