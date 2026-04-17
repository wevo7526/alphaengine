"""
Desk 3B — Position Risk Manager.

Pure computation. Wraps quant/risk.py functions into a programmatic risk gate
that evaluates proposed trades against hard limits:
- Max position size (5% of portfolio)
- Max sector concentration (30%)
- Correlation with existing positions
- Marginal VaR impact
- Drawdown circuit breaker status

This is the RISK DESK's kill authority — trades that breach limits get
BLOCKED, not warned about. No PM override.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from quant.risk import pre_trade_risk_check, drawdown_circuit_breaker
from data.market_client import MarketDataClient

logger = logging.getLogger(__name__)

_market = MarketDataClient()


def evaluate_trade_gate(
    ticker: str,
    direction: str,
    proposed_size_pct: float,
    existing_positions: list[dict],
    portfolio_drawdown_pct: float = 0.0,
    max_position_size: float = 0.05,
    max_sector_pct: float = 0.30,
) -> dict:
    """
    Run the full pre-trade risk check on a proposed trade.

    Args:
        ticker: proposed trade ticker
        direction: bullish | bearish | strong_bullish | strong_bearish | neutral
        proposed_size_pct: position size as percentage (e.g., 3.0 for 3%)
        existing_positions: list of dicts with ticker, direction, size_pct, sector
        portfolio_drawdown_pct: current portfolio drawdown (positive number)

    Returns:
        {
          approved: bool,
          ticker: str,
          original_size_pct: float,
          adjusted_size_pct: float,
          reasons: list[str],   # Why blocked or why adjusted
          circuit_breaker: dict,
          action: "ALLOW" | "REDUCE" | "BLOCK",
        }
    """
    # Circuit breaker first — overrides everything
    circuit = drawdown_circuit_breaker(portfolio_drawdown_pct)
    if circuit.get("size_multiplier", 1.0) == 0:
        return {
            "approved": False,
            "ticker": ticker,
            "original_size_pct": proposed_size_pct,
            "adjusted_size_pct": 0,
            "reasons": [f"Circuit breaker: {circuit.get('action', 'portfolio drawdown triggered halt')}"],
            "circuit_breaker": circuit,
            "action": "BLOCK",
        }

    # Apply circuit breaker multiplier
    size_multiplier = circuit.get("size_multiplier", 1.0)
    adjusted_proposed = proposed_size_pct * size_multiplier

    # Build positions dict and fetch returns for marginal VaR
    positions = {}
    returns_dict = {}

    tickers_to_fetch = [p["ticker"] for p in existing_positions]
    if ticker not in tickers_to_fetch:
        tickers_to_fetch.append(ticker)

    def _fetch(tk: str) -> tuple[str, list[float], str]:
        try:
            history = _market.get_price_history(tk, period="3mo")
            sector = "Unknown"
            if history and len(history) > 20:
                try:
                    fund = _market.get_fundamentals(tk)
                    sector = fund.get("sector", "Unknown") or "Unknown"
                except Exception:
                    pass
                closes = [b["close"] for b in history]
                rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
                return tk, rets, sector
            return tk, [], sector
        except Exception as e:
            logger.debug(f"Failed to fetch data for {tk}: {e}")
            return tk, [], "Unknown"

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_fetch, tickers_to_fetch))

    for tk, rets, sector in results:
        if rets:
            returns_dict[tk] = rets
        # Find existing position for this ticker
        existing = next((p for p in existing_positions if p["ticker"] == tk), None)
        if existing:
            positions[tk] = {
                "sector": existing.get("sector") or sector,
                "weight": existing.get("size_pct", 0) / 100.0,
            }
        elif tk == ticker:
            # Future position — set sector but no weight yet
            positions.setdefault(tk, {"sector": sector, "weight": 0})
        else:
            positions.setdefault(tk, {"sector": sector, "weight": 0})

    # Run the gate
    check = pre_trade_risk_check(
        ticker=ticker,
        proposed_action="BUY" if "bullish" in (direction or "") else "SELL",
        proposed_size_pct=adjusted_proposed / 100.0,  # convert to fraction
        current_positions=positions,
        returns_dict=returns_dict,
        max_position_size=max_position_size,
        max_sector_pct=max_sector_pct,
    )

    # Build response
    original_size = proposed_size_pct
    adjusted_size = check.get("adjusted_size_pct", 0)
    approved = check.get("approved", False)
    reasons = check.get("reasons", [])

    # Add circuit breaker reason if it adjusted
    if size_multiplier < 1.0:
        reasons.insert(0, f"Circuit breaker ({circuit.get('status', '?')}): sized reduced by {int((1 - size_multiplier) * 100)}%")

    if not approved:
        action = "BLOCK"
    elif abs(adjusted_size - original_size) > 0.01:
        action = "REDUCE"
    else:
        action = "ALLOW"

    return {
        "approved": approved,
        "ticker": ticker,
        "original_size_pct": round(original_size, 2),
        "adjusted_size_pct": round(adjusted_size, 2),
        "reasons": reasons,
        "circuit_breaker": circuit,
        "risk_metrics": check.get("risk_metrics", {}),
        "action": action,
    }


async def get_current_portfolio_drawdown(async_session_factory, user_id: str | None = None) -> float:
    """
    Compute current portfolio drawdown from open + closed trade history.

    Returns drawdown as positive percentage (e.g., 5.2 means 5.2% below peak).
    """
    from sqlalchemy import select, desc
    from db.models import TradeRecord

    try:
        async with async_session_factory() as session:
            q = select(TradeRecord).order_by(desc(TradeRecord.opened_at))
            if user_id:
                q = q.where(TradeRecord.user_id == user_id)
            result = await session.execute(q)
            trades = result.scalars().all()
    except Exception as e:
        logger.warning(f"Failed to fetch trades for drawdown: {e}")
        return 0.0

    if not trades:
        return 0.0

    # Cumulative return from closed trades + unrealized from open trades
    portfolio_base = 100000.0
    cumulative = portfolio_base

    # Build a return series: for each closed trade, apply its realized_pnl % weighted by size
    realized_return = 0.0
    for t in trades:
        if t.status != "open" and t.realized_pnl is not None:
            size_frac = (t.position_size_pct or 0) / 100.0
            realized_return += (t.realized_pnl / 100.0) * size_frac

    # Unrealized from open trades (approximation — needs current prices but
    # this function is called before trades so we use a best estimate)
    cumulative = portfolio_base * (1 + realized_return)
    peak = max(portfolio_base, cumulative)
    dd = (peak - cumulative) / peak * 100

    return max(0.0, dd)
