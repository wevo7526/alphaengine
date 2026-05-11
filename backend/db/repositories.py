"""
Async repository layer — CRUD operations for all DB models.
Keeps route handlers thin and quant modules testable.
"""

from sqlalchemy import select, desc, update
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime, timezone
import logging

from db.database import async_session
from db.models import (
    IntelligenceMemoRecord, TradeRecord, PortfolioSnapshotRecord,
    BacktestRunRecord, BacktestResultRecord, FactorExposureRecord,
    RegimeRecord, MacroSnapshotRecord,
)

logger = logging.getLogger(__name__)


class MemoRepository:
    @staticmethod
    async def save(memo_data: dict) -> str:
        async with async_session() as session:
            record = IntelligenceMemoRecord(**memo_data)
            session.add(record)
            await session.commit()
            return record.id

    @staticmethod
    async def get_latest(limit: int = 20) -> list[dict]:
        async with async_session() as session:
            result = await session.execute(
                select(IntelligenceMemoRecord)
                .order_by(desc(IntelligenceMemoRecord.created_at))
                .limit(limit)
            )
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in result.scalars().all()
            ]

    @staticmethod
    async def get_by_id(memo_id: str) -> dict | None:
        """Fetch a single memo by id. Returns None when not found."""
        async with async_session() as session:
            result = await session.execute(
                select(IntelligenceMemoRecord).where(IntelligenceMemoRecord.id == memo_id)
            )
            r = result.scalar_one_or_none()
            if r is None:
                return None
            return {c.name: getattr(r, c.name) for c in r.__table__.columns}

    @staticmethod
    async def get_thread(thread_id: str) -> list[dict]:
        """
        Return all memos in a thread, ordered by sequence_in_thread.
        Used by the orchestrator to load the full conversational context.
        """
        async with async_session() as session:
            result = await session.execute(
                select(IntelligenceMemoRecord)
                .where(IntelligenceMemoRecord.thread_id == thread_id)
                .order_by(IntelligenceMemoRecord.sequence_in_thread.asc())
            )
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in result.scalars().all()
            ]

    @staticmethod
    async def resolve_thread_for_parent(parent_memo_id: str | None) -> tuple[str | None, str | None, int]:
        """
        Given a parent_memo_id (or None for a fresh thread), return:
            (thread_id, parent_memo_id, sequence_in_thread)
        For a fresh thread, thread_id is None — the orchestrator will set
        it to the newly created memo's id after save (single-memo thread).
        For a continuation, thread_id propagates from the parent and sequence
        increments.
        """
        if not parent_memo_id:
            return None, None, 0
        async with async_session() as session:
            result = await session.execute(
                select(IntelligenceMemoRecord).where(
                    IntelligenceMemoRecord.id == parent_memo_id
                )
            )
            parent = result.scalar_one_or_none()
            if parent is None:
                logger.warning(f"parent_memo_id={parent_memo_id} not found — starting new thread")
                return None, None, 0
            parent_thread_id = getattr(parent, "thread_id", None) or parent.id
            parent_seq = int(getattr(parent, "sequence_in_thread", 0) or 0)
            return parent_thread_id, parent.id, parent_seq + 1

    @staticmethod
    async def get_recent_tickers_for_user(
        user_id: str | None, days: int = 14, limit_memos: int = 50,
    ) -> list[str]:
        """
        Return the set of tickers the user has seen in memos within the last
        `days` days. Used by the screening layer to penalize already-proposed
        names (anti-repetition) — a name appearing for the 3rd time in 14 days
        is signal-stale, not fresh alpha. Returns [] when no memos found.

        Aggregates tickers from both `tickers_analyzed` and `trade_ideas[].ticker`
        because the user may have seen a name as supporting context (analyzed)
        or as an actionable idea — either way it's in their recent attention.
        """
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=int(max(1, days)))
        async with async_session() as session:
            query = (
                select(IntelligenceMemoRecord)
                .order_by(desc(IntelligenceMemoRecord.created_at))
                .limit(limit_memos)
            )
            if user_id:
                query = query.where(IntelligenceMemoRecord.user_id == user_id)
            try:
                result = await session.execute(query)
            except Exception as e:
                logger.warning(f"get_recent_tickers_for_user query failed: {e}")
                return []
            seen: set[str] = set()
            for r in result.scalars().all():
                created = getattr(r, "created_at", None)
                if created is not None:
                    # SQLAlchemy may return naive datetimes from SQLite even
                    # though the column is TIMESTAMPTZ on Postgres. Normalize.
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    if created < cutoff:
                        continue
                analyzed = getattr(r, "tickers_analyzed", None) or []
                if isinstance(analyzed, list):
                    for t in analyzed:
                        if isinstance(t, str) and t.strip():
                            seen.add(t.strip().upper())
                ideas = getattr(r, "trade_ideas", None) or []
                if isinstance(ideas, list):
                    for idea in ideas:
                        if isinstance(idea, dict):
                            t = idea.get("ticker")
                            if isinstance(t, str) and t.strip():
                                seen.add(t.strip().upper())
            return sorted(seen)


class TradeRepository:
    @staticmethod
    async def save(trade_data: dict) -> str:
        async with async_session() as session:
            record = TradeRecord(**trade_data)
            session.add(record)
            await session.commit()
            return record.id

    @staticmethod
    async def get_trades(status: str = "all", limit: int = 50) -> list[dict]:
        async with async_session() as session:
            query = select(TradeRecord).order_by(desc(TradeRecord.opened_at))
            if status != "all":
                query = query.where(TradeRecord.status == status)
            result = await session.execute(query.limit(limit))
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in result.scalars().all()
            ]

    @staticmethod
    async def close_trade(trade_id: str, exit_price: float, pnl: float):
        async with async_session() as session:
            await session.execute(
                update(TradeRecord)
                .where(TradeRecord.id == trade_id)
                .values(status="closed", exit_price=exit_price, realized_pnl=pnl, closed_at=datetime.now(timezone.utc))
            )
            await session.commit()


class BacktestRepository:
    @staticmethod
    async def save_run(run_data: dict) -> str:
        async with async_session() as session:
            record = BacktestRunRecord(**run_data)
            session.add(record)
            await session.commit()
            return record.id

    @staticmethod
    async def update_run_status(run_id: str, status: str, error: str = None):
        async with async_session() as session:
            values = {"status": status}
            if error:
                values["error_message"] = error
            await session.execute(
                update(BacktestRunRecord).where(BacktestRunRecord.id == run_id).values(**values)
            )
            await session.commit()

    @staticmethod
    async def save_results(results_data: dict) -> str:
        async with async_session() as session:
            record = BacktestResultRecord(**results_data)
            session.add(record)
            await session.commit()
            return record.id

    @staticmethod
    async def get_runs(limit: int = 20) -> list[dict]:
        async with async_session() as session:
            result = await session.execute(
                select(BacktestRunRecord).order_by(desc(BacktestRunRecord.created_at)).limit(limit)
            )
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in result.scalars().all()
            ]

    @staticmethod
    async def get_results(run_id: str) -> dict | None:
        async with async_session() as session:
            result = await session.execute(
                select(BacktestResultRecord).where(BacktestResultRecord.backtest_run_id == run_id)
            )
            r = result.scalar_one_or_none()
            if not r:
                return None
            return {c.name: getattr(r, c.name) for c in r.__table__.columns}


class SnapshotRepository:
    @staticmethod
    async def save(snapshot_data: dict):
        async with async_session() as session:
            record = PortfolioSnapshotRecord(**snapshot_data)
            session.add(record)
            await session.commit()

    @staticmethod
    async def get_equity_curve(start: date, end: date) -> list[dict]:
        async with async_session() as session:
            result = await session.execute(
                select(PortfolioSnapshotRecord)
                .where(PortfolioSnapshotRecord.snapshot_date.between(start, end))
                .order_by(PortfolioSnapshotRecord.snapshot_date)
            )
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in result.scalars().all()
            ]
