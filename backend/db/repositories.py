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
    PositionSnapshotRecord,
    BacktestRunRecord, BacktestResultRecord, FactorExposureRecord,
    RegimeRecord, MacroSnapshotRecord, UserProfile, UserRiskProfile,
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


class UserProfileRepository:
    """CRUD for per-user onboarding profiles."""

    @staticmethod
    async def get(user_id: str) -> dict | None:
        async with async_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            r = result.scalar_one_or_none()
            if r is None:
                return None
            return {c.name: getattr(r, c.name) for c in r.__table__.columns}

    @staticmethod
    async def upsert(user_id: str, fields: dict) -> dict:
        """
        Upsert profile fields for a user. Returns the resulting row as a dict.
        Allowed fields: full_name, email, role, portfolio_size_usd, benchmark,
        mandate, onboarded_at. Anything else is ignored.
        """
        allowed = {
            "full_name", "email", "role",
            "portfolio_size_usd", "benchmark", "mandate", "onboarded_at",
            "entitlement",  # demo | trial | paid (see USER_STATES.md)
        }
        clean = {k: v for k, v in fields.items() if k in allowed}

        async with async_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = UserProfile(user_id=user_id, **clean)
                session.add(row)
            else:
                for k, v in clean.items():
                    setattr(row, k, v)
            await session.commit()
            await session.refresh(row)
            return {c.name: getattr(row, c.name) for c in row.__table__.columns}

    @staticmethod
    async def mark_onboarded(user_id: str, fields: dict | None = None) -> dict:
        """Set onboarded_at to now and optionally update other fields."""
        from datetime import datetime, timezone as tz
        merged = dict(fields or {})
        merged["onboarded_at"] = datetime.now(tz.utc)
        return await UserProfileRepository.upsert(user_id, merged)


# Whitelist of editable risk-override fields. Must match UserRiskProfile
# columns exactly. Anything not in this set is silently dropped at upsert
# time to prevent stray column writes.
USER_RISK_FIELDS = frozenset({
    "max_position_pct", "max_sector_pct", "min_position_pct",
    "var_confidence",
    "drawdown_caution_pct", "drawdown_warn_pct", "drawdown_critical_pct",
    "marginal_var_block_pct", "silent_squeeze_threshold",
    "liquidity_max_pct_of_adv", "liquidity_block_pct_of_adv",
    "liquidity_participation_rate", "liquidity_spread_warn_bps",
    "optimizer_tx_cost_bps", "optimizer_ridge_lambda",
    "vif_max_threshold",
})


class UserRiskProfileRepository:
    """
    CRUD for per-user overrides of the platform's risk gates.

    Every field is nullable — NULL means "use the platform default".
    Upsert only touches fields explicitly present in the input dict; pass
    {field: None} to reset a single field back to the platform default.
    """

    @staticmethod
    async def get(user_id: str) -> dict | None:
        async with async_session() as session:
            result = await session.execute(
                select(UserRiskProfile).where(UserRiskProfile.user_id == user_id)
            )
            r = result.scalar_one_or_none()
            if r is None:
                return None
            return {c.name: getattr(r, c.name) for c in r.__table__.columns}

    @staticmethod
    async def upsert(user_id: str, fields: dict) -> dict:
        """
        Update only the explicitly-present fields. Pass {key: None} to
        clear an override and fall back to the platform default. Fields
        outside USER_RISK_FIELDS are ignored.
        """
        clean = {k: v for k, v in fields.items() if k in USER_RISK_FIELDS}

        async with async_session() as session:
            result = await session.execute(
                select(UserRiskProfile).where(UserRiskProfile.user_id == user_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                row = UserRiskProfile(user_id=user_id, **clean)
                session.add(row)
            else:
                for k, v in clean.items():
                    setattr(row, k, v)
            await session.commit()
            await session.refresh(row)
            return {c.name: getattr(row, c.name) for c in row.__table__.columns}

    @staticmethod
    async def reset(user_id: str) -> None:
        """Wipe all user overrides — equivalent to falling back to all defaults."""
        async with async_session() as session:
            result = await session.execute(
                select(UserRiskProfile).where(UserRiskProfile.user_id == user_id)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return
            for f in USER_RISK_FIELDS:
                setattr(row, f, None)
            await session.commit()


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
    """EOD portfolio + position snapshot persistence + reads.

    Every method that reads or writes filters by user_id. The legacy
    get_equity_curve() that didn't filter was a multi-tenant bug —
    fixed here by making user_id required.
    """

    @staticmethod
    async def save(snapshot_data: dict):
        """Legacy insert. Kept for back-compat; new code uses upsert_*."""
        async with async_session() as session:
            record = PortfolioSnapshotRecord(**snapshot_data)
            session.add(record)
            await session.commit()

    @staticmethod
    async def upsert_portfolio(row: dict):
        """Insert or update one portfolio_snapshots row by (user_id, date).

        The unique index `ix_portfolio_snapshots_user_date` makes the
        SELECT-then-INSERT/UPDATE pattern safe across reruns.
        """
        from datetime import datetime as _dt, timezone as _tz
        user_id = row.get("user_id")
        snapshot_date = row.get("snapshot_date")
        async with async_session() as session:
            result = await session.execute(
                select(PortfolioSnapshotRecord).where(
                    PortfolioSnapshotRecord.user_id == user_id,
                    PortfolioSnapshotRecord.snapshot_date == snapshot_date,
                )
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                record = PortfolioSnapshotRecord(**row)
                session.add(record)
            else:
                for k, v in row.items():
                    if k in ("user_id", "snapshot_date", "id"):
                        continue
                    setattr(existing, k, v)
                existing.updated_at = _dt.now(_tz.utc)
            await session.commit()

    @staticmethod
    async def upsert_positions(rows: list[dict]):
        """Insert or update many position_snapshots rows by
        (trade_id, snapshot_date). Batched in a single transaction.
        """
        if not rows:
            return
        from db.models import PositionSnapshotRecord
        async with async_session() as session:
            for row in rows:
                trade_id = row.get("trade_id")
                snapshot_date = row.get("snapshot_date")
                result = await session.execute(
                    select(PositionSnapshotRecord).where(
                        PositionSnapshotRecord.trade_id == trade_id,
                        PositionSnapshotRecord.snapshot_date == snapshot_date,
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is None:
                    session.add(PositionSnapshotRecord(**row))
                else:
                    for k, v in row.items():
                        if k in ("trade_id", "snapshot_date", "id"):
                            continue
                        setattr(existing, k, v)
            await session.commit()

    @staticmethod
    async def get_equity_curve(
        user_id: str,
        start: date | None = None,
        end: date | None = None,
        days: int | None = None,
    ) -> list[dict]:
        """User-scoped equity curve time series.

        Either pass `start`+`end` explicitly, or pass `days` to get the
        most-recent N days ending today. The legacy unscoped signature
        was a multi-tenant bug — user_id is now required.
        """
        from datetime import date as _date, timedelta as _td
        if days is not None:
            end = end or _date.today()
            start = end - _td(days=int(days))
        q = select(PortfolioSnapshotRecord).where(
            PortfolioSnapshotRecord.user_id == user_id,
        )
        if start is not None:
            q = q.where(PortfolioSnapshotRecord.snapshot_date >= start)
        if end is not None:
            q = q.where(PortfolioSnapshotRecord.snapshot_date <= end)
        q = q.order_by(PortfolioSnapshotRecord.snapshot_date)
        async with async_session() as session:
            result = await session.execute(q)
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in result.scalars().all()
            ]

    @staticmethod
    async def get_latest_before(user_id: str, on_or_before: date) -> dict | None:
        """Return the most recent portfolio snapshot strictly before
        `on_or_before` — used by the EOD engine to compute daily delta.
        """
        from sqlalchemy import desc
        async with async_session() as session:
            result = await session.execute(
                select(PortfolioSnapshotRecord)
                .where(
                    PortfolioSnapshotRecord.user_id == user_id,
                    PortfolioSnapshotRecord.snapshot_date < on_or_before,
                )
                .order_by(desc(PortfolioSnapshotRecord.snapshot_date))
                .limit(1)
            )
            r = result.scalar_one_or_none()
            if r is None:
                return None
            return {c.name: getattr(r, c.name) for c in r.__table__.columns}

    @staticmethod
    async def get_position_history(
        user_id: str,
        trade_id: str,
        days: int = 30,
    ) -> list[dict]:
        """User-scoped position pnl history. Drives per-position sparkline."""
        from datetime import date as _date, timedelta as _td
        from sqlalchemy import asc
        from db.models import PositionSnapshotRecord
        start = _date.today() - _td(days=int(days))
        async with async_session() as session:
            result = await session.execute(
                select(PositionSnapshotRecord)
                .where(
                    PositionSnapshotRecord.user_id == user_id,
                    PositionSnapshotRecord.trade_id == trade_id,
                    PositionSnapshotRecord.snapshot_date >= start,
                )
                .order_by(asc(PositionSnapshotRecord.snapshot_date))
            )
            return [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in result.scalars().all()
            ]

    @staticmethod
    async def get_position_history_bulk(
        user_id: str,
        trade_ids: list[str],
        days: int = 30,
    ) -> dict[str, list[dict]]:
        """Bulk read for all open trades — avoids N+1 on the positions endpoint."""
        from datetime import date as _date, timedelta as _td
        from sqlalchemy import asc
        from db.models import PositionSnapshotRecord
        if not trade_ids:
            return {}
        start = _date.today() - _td(days=int(days))
        out: dict[str, list[dict]] = {tid: [] for tid in trade_ids}
        async with async_session() as session:
            result = await session.execute(
                select(PositionSnapshotRecord)
                .where(
                    PositionSnapshotRecord.user_id == user_id,
                    PositionSnapshotRecord.trade_id.in_(trade_ids),
                    PositionSnapshotRecord.snapshot_date >= start,
                )
                .order_by(asc(PositionSnapshotRecord.snapshot_date))
            )
            for r in result.scalars().all():
                row = {c.name: getattr(r, c.name) for c in r.__table__.columns}
                tid = row["trade_id"]
                if tid in out:
                    out[tid].append(row)
        return out
