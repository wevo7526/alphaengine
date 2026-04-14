"""
Backtesting module — evaluate trade idea accuracy against actual price outcomes.

Checks each open trade's current price vs entry/stop/target and computes P&L.
"""

import logging
from datetime import datetime
from data.market_client import MarketDataClient

logger = logging.getLogger(__name__)

_market = MarketDataClient()


def evaluate_trade(trade: dict) -> dict:
    """
    Evaluate a single trade against current market price.
    Returns the trade enriched with current_price, unrealized_pnl, hit_target, hit_stop.
    """
    ticker = trade.get("ticker", "")
    if not ticker:
        return {**trade, "evaluation": {"error": "No ticker"}}

    try:
        fundamentals = _market.get_fundamentals(ticker)
        current_price = fundamentals.get("current_price")
        if not current_price:
            return {**trade, "evaluation": {"error": "No price data"}}

        entry_price = trade.get("entry_price")
        stop_loss = trade.get("stop_loss")
        take_profit = trade.get("take_profit")
        direction = trade.get("direction", "")

        is_long = "bullish" in direction
        is_short = "bearish" in direction

        # Compute unrealized P&L
        pnl_pct = None
        if entry_price and entry_price > 0:
            if is_long:
                pnl_pct = round((current_price - entry_price) / entry_price * 100, 2)
            elif is_short:
                pnl_pct = round((entry_price - current_price) / entry_price * 100, 2)

        # Check stop/target hits
        hit_stop = False
        hit_target = False
        if is_long:
            if stop_loss and current_price <= stop_loss:
                hit_stop = True
            if take_profit and current_price >= take_profit:
                hit_target = True
        elif is_short:
            if stop_loss and current_price >= stop_loss:
                hit_stop = True
            if take_profit and current_price <= take_profit:
                hit_target = True

        return {
            **trade,
            "evaluation": {
                "current_price": current_price,
                "unrealized_pnl_pct": pnl_pct,
                "hit_stop": hit_stop,
                "hit_target": hit_target,
                "status": "target_hit" if hit_target else "stopped_out" if hit_stop else "open",
                "evaluated_at": datetime.utcnow().isoformat(),
            },
        }
    except Exception as e:
        logger.warning(f"Backtest eval failed for {ticker}: {e}")
        return {**trade, "evaluation": {"error": str(e)}}


def evaluate_trades(trades: list[dict]) -> list[dict]:
    """Evaluate a list of trades. Returns them enriched with evaluations."""
    return [evaluate_trade(t) for t in trades]
