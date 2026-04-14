"""
Async repository layer — CRUD operations for all DB models.
Keeps route handlers thin and quant modules testable.
"""

from sqlalchemy import select, desc, update
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, datetime
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
                .values(status="closed", exit_price=exit_price, realized_pnl=pnl, closed_at=datetime.utcnow())
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
