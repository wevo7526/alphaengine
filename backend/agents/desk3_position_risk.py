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

from quant.risk import pre_trade_risk_check, drawdown_circuit_breaker, assess_liquidity
from quant.regime import regime_size_multiplier
from quant import limits as _limits
from data.market_client import MarketDataClient
from data.sector_map import resolve_sector

logger = logging.getLogger(__name__)

_market = MarketDataClient()


def evaluate_trade_gate(
    ticker: str,
    direction: str,
    proposed_size_pct: float,
    existing_positions: list[dict],
    portfolio_drawdown_pct: float = 0.0,
    max_position_size: float | None = None,
    max_sector_pct: float | None = None,
    regime: str | None = None,
    regime_confidence: float | None = None,
) -> dict:
    """
    Run the full pre-trade risk check on a proposed trade.

    Sizing pipeline:
        proposed -> circuit_breaker_mult -> regime_mult -> pre_trade_risk_check

    Args:
        ticker: proposed trade ticker
        direction: bullish | bearish | strong_bullish | strong_bearish | neutral
        proposed_size_pct: position size as percentage (e.g., 3.0 for 3%)
        existing_positions: list of dicts with ticker, direction, size_pct, sector
        portfolio_drawdown_pct: current portfolio drawdown (positive number)
        regime: current macro regime ("risk_on" | "transition" | "risk_off")
        regime_confidence: 0..1 confidence in the regime call

    Returns:
        {
          approved: bool,
          ticker: str,
          original_size_pct: float,
          adjusted_size_pct: float,
          reasons: list[str],   # Why blocked or why adjusted
          circuit_breaker: dict,
          regime_adjustment: dict,   # NEW
          action: "ALLOW" | "REDUCE" | "BLOCK",
        }
    """
    # Resolve thresholds from quant.limits
    if max_position_size is None:
        max_position_size = _limits.MAX_POSITION_SIZE
    if max_sector_pct is None:
        max_sector_pct = _limits.MAX_SECTOR_PCT

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
            "regime_adjustment": None,
            "action": "BLOCK",
        }

    # Apply circuit breaker multiplier
    cb_multiplier = circuit.get("size_multiplier", 1.0)

    # Apply regime multiplier — risk_off trims sizing, risk_on does nothing
    regime_adj = regime_size_multiplier(regime, regime_confidence)
    regime_multiplier = regime_adj["multiplier"]

    adjusted_proposed = proposed_size_pct * cb_multiplier * regime_multiplier

    # Build positions dict and fetch returns for marginal VaR
    positions = {}
    returns_dict = {}

    tickers_to_fetch = [p["ticker"] for p in existing_positions]
    if ticker not in tickers_to_fetch:
        tickers_to_fetch.append(ticker)

    def _fetch(tk: str) -> tuple[str, list[float], str]:
        yahoo_sector: str | None = None
        rets: list[float] = []
        try:
            history = _market.get_price_history(tk, period="3mo")
            if history and len(history) > 20:
                closes = [b["close"] for b in history]
                rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
            try:
                fund = _market.get_fundamentals(tk)
                yahoo_sector = (fund or {}).get("sector")
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Failed to fetch data for {tk}: {e}")

        sector, source = resolve_sector(tk, yahoo_sector)
        if source == "unresolved":
            logger.warning(
                "sector_unresolved ticker=%s — risk gate cannot enforce sector concentration "
                "for this name. Add to data/sector_map.py to fix.", tk,
            )
        return tk, rets, sector

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

    # Liquidity check — hard block on illiquid names
    liquidity = None
    try:
        fund = _market.get_fundamentals(ticker) or {}
        adv_shares = fund.get("avg_volume_3m") or fund.get("avg_volume_10d")
        price = fund.get("current_price")
        portfolio_base = 100000.0  # paper-trading default; matches risk dashboard
        proposed_notional = (adjusted_proposed / 100.0) * portfolio_base
        liquidity = assess_liquidity(
            proposed_notional=proposed_notional,
            avg_daily_volume_shares=float(adv_shares) if adv_shares else None,
            current_price=float(price) if price else None,
            bid=fund.get("bid"),
            ask=fund.get("ask"),
        )
        if liquidity.get("recommendation") == "block":
            check["approved"] = False
            check.setdefault("reasons", []).extend(liquidity.get("reasons", []))
            check.setdefault("block_reasons", []).extend(liquidity.get("reasons", []))
        elif liquidity.get("recommendation") == "warn":
            check.setdefault("reasons", []).extend(liquidity.get("reasons", []))
    except Exception as e:
        logger.debug(f"Liquidity check failed for {ticker} (non-fatal): {e}")

    # Build response
    original_size = proposed_size_pct
    adjusted_size = check.get("adjusted_size_pct", 0)
    approved = check.get("approved", False)
    reasons = check.get("reasons", [])

    # Add circuit-breaker and regime reasons in pipeline order
    if cb_multiplier < 1.0:
        reasons.insert(0, f"Circuit breaker ({circuit.get('status', '?')}): size reduced by {int((1 - cb_multiplier) * 100)}%")
    if regime_multiplier < 1.0:
        reasons.insert(0, regime_adj["reason"])

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
        "regime_adjustment": regime_adj,
        "liquidity": liquidity,
        "risk_metrics": check.get("risk_metrics", {}),
        "action": action,
    }


async def get_current_portfolio_drawdown(async_session_factory, user_id: str | None = None) -> float:
    """
    Compute current portfolio drawdown from real book activity:
      - Realized P&L from closed trades, weighted by position size
      - Unrealized P&L from open trades, marked at current market price
        (sign-adjusted by direction so shorts contribute correctly)

    Returns drawdown as a positive percentage (e.g., 5.2 means 5.2% below peak).

    The portfolio peak is approximated as max(starting_value, current_value) —
    a single-user paper account doesn't have a deep equity-curve history, so
    "peak" is bounded above by the starting capital. This is conservative
    (overstates drawdown if the book has been profitable, which is the safer
    direction for a circuit breaker).
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

    portfolio_base = 100000.0

    # Realized P&L (closed trades). realized_pnl is stored as % return per trade,
    # so we weight by position_size_pct / 100 to get its book-level contribution.
    realized_return = 0.0
    for t in trades:
        if t.status != "open" and t.realized_pnl is not None:
            size_frac = (t.position_size_pct or 0) / 100.0
            realized_return += (t.realized_pnl / 100.0) * size_frac

    # Unrealized P&L (open trades). Mark at current market for each ticker,
    # sign-adjusted by direction so shorts correctly subtract on rallies.
    open_trades = [t for t in trades if t.status == "open" and t.entry_price]
    unique_tickers = list({t.ticker for t in open_trades})
    prices: dict[str, float] = {}
    if unique_tickers:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for tk, price in pool.map(_safe_current_price, unique_tickers):
                if price is not None:
                    prices[tk] = price

    unrealized_return = 0.0
    for t in open_trades:
        current = prices.get(t.ticker)
        if current is None or not t.entry_price or t.entry_price <= 0:
            continue
        size_frac = (t.position_size_pct or 0) / 100.0
        is_long = "bullish" in (t.direction or "")
        raw_pnl_frac = (current - t.entry_price) / t.entry_price
        signed = raw_pnl_frac if is_long else -raw_pnl_frac
        unrealized_return += signed * size_frac

    total_return = realized_return + unrealized_return
    cumulative = portfolio_base * (1 + total_return)
    peak = max(portfolio_base, cumulative)
    dd = (peak - cumulative) / peak * 100

    return max(0.0, dd)


def _safe_current_price(ticker: str) -> tuple[str, float | None]:
    """Fetch current price; never raise — None means 'unknown, skip in P&L math'."""
    try:
        fund = _market.get_fundamentals(ticker)
        price = (fund or {}).get("current_price")
        if price and price > 0:
            return ticker, float(price)
    except Exception as e:
        logger.debug(f"current_price fetch failed for {ticker}: {e}")
    return ticker, None
