"""
infra/eod_snapshot.py — End-of-day portfolio snapshot engine.

Builds two records per user per trading day:

  1. position_snapshots — one row per open trade with close_price,
     unrealized_pnl_pct, unrealized_pnl_dollars, days_held. This is
     the raw material for per-position sparklines and contribution
     analysis.

  2. portfolio_snapshots — one rollup row per user per day with the
     full portfolio state (market_value, cumulative_pnl, etc.). This
     drives the equity curve on the portfolio page.

Both writes are idempotent on (user_id|trade_id, snapshot_date) via
unique indexes — rerunning the EOD job on the same day overwrites
instead of duplicating.

Triggered by:
  - User action: POST /api/portfolio/snapshot/run (manual "snapshot now")
  - Cron: Railway scheduled task hitting the same endpoint daily after
    market close (4:30 PM EST after yfinance settles)

Per-user cost: one batch yfinance call across all open tickers + ~N
DB upserts where N = open position count. Fast enough to run inline
on a request thread — no need for background queue.
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timezone
from typing import Any

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def compute_eod_snapshot(
    user_id: str,
    snapshot_date: date | None = None,
) -> dict:
    """Compute and persist the EOD snapshot for one user.

    Returns the persisted portfolio rollup dict (the row that the
    equity-curve endpoint will later read). Never raises — on partial
    failure (e.g. yfinance times out on one ticker) we persist what
    we have and surface a `warnings` field for the caller.
    """
    if snapshot_date is None:
        # Default to the trading day in America/New_York. Using the user's
        # timezone here would race with the cron schedule; New York is the
        # canonical anchor for US equity sessions.
        snapshot_date = _ny_today()

    from db.database import async_session
    from db.models import TradeRecord
    from data.market_client import MarketDataClient
    from infra.user_context import resolve_portfolio_base
    from db.repositories import SnapshotRepository

    warnings: list[str] = []
    portfolio_base = await resolve_portfolio_base(user_id)

    # ── Read trades ────────────────────────────────────────────────
    open_trades: list[Any] = []
    closed_trades: list[Any] = []
    try:
        async with async_session() as session:
            result = await session.execute(
                select(TradeRecord).where(TradeRecord.user_id == user_id)
            )
            for t in result.scalars().all():
                if t.status == "open":
                    open_trades.append(t)
                else:
                    closed_trades.append(t)
    except Exception as e:
        logger.warning(f"eod_snapshot trades read failed for {user_id}: {e}")
        warnings.append(f"trades read failed: {e}")

    # ── Fetch close prices ─────────────────────────────────────────
    tickers = list({t.ticker for t in open_trades if t.ticker})
    prices = _batch_close_prices(tickers, warnings)

    # ── Per-position rollup ────────────────────────────────────────
    total_market_value = 0.0
    total_cost_basis = 0.0
    total_unrealized_pnl = 0.0
    positions_json: list[dict] = []
    position_rows: list[dict] = []
    for t in open_trades:
        entry = float(t.entry_price or 0)
        size_pct = float(t.position_size_pct or 0)
        if not (entry > 0 and size_pct > 0):
            continue
        close = prices.get(t.ticker)
        if close is None:
            # No price available — snapshot a flat row so the per-position
            # series stays continuous (gap-fill on the frontend).
            warnings.append(f"no close price for {t.ticker}")
            close = entry

        is_long = "bullish" in (t.direction or "").lower()
        is_short = "bearish" in (t.direction or "").lower()
        if is_long:
            pnl_pct = (close - entry) / entry * 100
        elif is_short:
            pnl_pct = (entry - close) / entry * 100
        else:
            pnl_pct = 0.0

        cost_basis = portfolio_base * size_pct / 100.0
        pnl_dollars = cost_basis * pnl_pct / 100.0
        market_value = cost_basis + pnl_dollars
        days_held = _days_since(t.opened_at)

        total_market_value += market_value
        total_cost_basis += cost_basis
        total_unrealized_pnl += pnl_dollars

        positions_json.append({
            "trade_id": t.id,
            "ticker": t.ticker,
            "direction": t.direction,
            "entry_price": round(entry, 4),
            "close_price": round(float(close), 4),
            "position_size_pct": round(size_pct, 4),
            "unrealized_pnl_pct": round(pnl_pct, 4),
            "unrealized_pnl_dollars": round(pnl_dollars, 2),
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "days_held": days_held,
        })
        position_rows.append({
            "user_id": user_id,
            "trade_id": t.id,
            "ticker": t.ticker,
            "direction": t.direction,
            "snapshot_date": snapshot_date,
            "entry_price": round(entry, 4),
            "close_price": round(float(close), 4),
            "position_size_pct": round(size_pct, 4),
            "unrealized_pnl_pct": round(pnl_pct, 4),
            "unrealized_pnl_dollars": round(pnl_dollars, 2),
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "days_held": days_held,
        })

    # ── Realized P&L from closed trades ────────────────────────────
    realized_pnl = 0.0
    for t in closed_trades:
        if t.realized_pnl is None:
            continue
        size_pct = float(t.position_size_pct or 0)
        # realized_pnl on the record is stored as a % return per trade;
        # weight by position size against the user's book.
        realized_pnl += (float(t.realized_pnl) / 100.0) * (portfolio_base * size_pct / 100.0)

    # Equity = base + realized + unrealized. The base is treated as the
    # starting capital; cumulative_pnl is the absolute return above it.
    cumulative_pnl = realized_pnl + total_unrealized_pnl
    equity_value = portfolio_base + cumulative_pnl
    cumulative_pnl_pct = (cumulative_pnl / portfolio_base * 100.0) if portfolio_base > 0 else 0.0

    # Day-over-day delta — look up the prior snapshot for the same user.
    prior = await SnapshotRepository.get_latest_before(user_id, snapshot_date)
    if prior:
        prior_equity = float(prior.get("total_value") or portfolio_base)
        daily_pnl = equity_value - prior_equity
        daily_pnl_pct = (daily_pnl / prior_equity * 100.0) if prior_equity > 0 else 0.0
    else:
        daily_pnl = 0.0
        daily_pnl_pct = 0.0

    portfolio_row = {
        "user_id": user_id,
        "snapshot_date": snapshot_date,
        "total_value": round(equity_value, 2),
        "cash": round(portfolio_base - total_cost_basis, 2),
        "positions_value": round(total_market_value, 2),
        "daily_pnl": round(daily_pnl, 2),
        "daily_pnl_pct": round(daily_pnl_pct, 4),
        "cumulative_pnl": round(cumulative_pnl, 2),
        "cumulative_pnl_pct": round(cumulative_pnl_pct, 4),
        "positions_json": positions_json,
    }

    # ── Persist (idempotent upsert) ────────────────────────────────
    try:
        await SnapshotRepository.upsert_portfolio(portfolio_row)
        if position_rows:
            await SnapshotRepository.upsert_positions(position_rows)
    except Exception as e:
        logger.exception(f"eod_snapshot persist failed for {user_id}: {e}")
        warnings.append(f"persist failed: {e}")
        return {**portfolio_row, "warnings": warnings, "persisted": False}

    return {
        **portfolio_row,
        "warnings": warnings,
        "persisted": True,
        "snapshot_date": snapshot_date.isoformat(),
    }


# ─── Helpers ────────────────────────────────────────────────────────


def _ny_today() -> date:
    """Today's date in America/New_York — the trading-day anchor."""
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo("America/New_York")).date()
    except Exception:
        # Fallback: UTC. Worst case the snapshot is tagged with the UTC
        # date instead of NY date — only matters in the few hours after
        # midnight UTC, and snapshots typically run after the close.
        return datetime.now(timezone.utc).date()


def _days_since(opened_at: Any) -> int:
    if opened_at is None:
        return 0
    try:
        if isinstance(opened_at, datetime):
            d0 = opened_at.date() if opened_at.tzinfo is None else opened_at.astimezone(timezone.utc).date()
        else:
            d0 = opened_at
        return max(0, (_ny_today() - d0).days)
    except Exception:
        return 0


def _batch_close_prices(tickers: list[str], warnings: list[str]) -> dict[str, float]:
    """Most-recent close price for a batch of tickers in ONE Massive call.

    Sources from Massive's grouped-daily tape (the whole market's closes in a
    single request) instead of get_fundamentals-per-ticker. Pricing N positions
    costs 1 call, not 4N — critical under the 5/min budget (this is why the
    portfolio stopped marking). Falls back to prev_close only for names absent
    from the tape.
    """
    if not tickers:
        return {}
    from data import massive_client
    try:
        out = {tk: float(px) for tk, px in (massive_client.last_prices(tickers) or {}).items() if px and px > 0}
    except Exception as e:  # noqa: BLE001
        warnings.append(f"bulk price fetch failed: {e}")
        out = {}
    # Per-ticker fallback only for the few names missing from the tape.
    for tk in tickers:
        u = (tk or "").strip().upper()
        if u and u not in out:
            try:
                px = massive_client.last_price(u)
                if px and px > 0:
                    out[u] = float(px)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"price fetch failed for {u}: {e}")
    return out
