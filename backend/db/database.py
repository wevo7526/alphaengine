"""
Database connection layer — async SQLAlchemy with asyncpg for Postgres.

For local dev without Postgres, falls back to SQLite (aiosqlite) and sets
a flag so the rest of the app can inspect what it's actually talking to.
Railway provides DATABASE_URL automatically when you add the Postgres plugin.

Production pool config is explicit — defaults are too small for multi-worker
Uvicorn deployments. Under 4 workers each doing 10 concurrent streams,
the default 5-connection pool exhausts in seconds and requests hang waiting
for a free connection.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _resolve_url() -> tuple[str, str]:
    """
    Return (effective_url, dialect). Dialect is 'postgres' or 'sqlite'.

    In production ENV, a default/empty DATABASE_URL is a hard failure signal —
    we log loudly but still fall back to SQLite so the app can start for
    diagnostics. A health check must report this state as degraded.
    """
    url = settings.DATABASE_URL or ""
    default_local = "postgresql+asyncpg://postgres:postgres@localhost:5432/alphaengine"
    if not url or url == default_local:
        if settings.ENV == "production":
            logger.error(
                "DATABASE_URL not configured in production — falling back to SQLite. "
                "Data will NOT persist across container restarts. Fix this immediately."
            )
        else:
            logger.info("No Postgres configured, using SQLite for local development")
        return "sqlite+aiosqlite:///./alphaengine.db", "sqlite"
    # Railway provides postgresql:// — convert to postgresql+asyncpg://.
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url, "postgres"


_db_url, DB_DIALECT = _resolve_url()
logger.info(f"Database URL resolved: {_db_url[:30]}... dialect={DB_DIALECT}")


def _engine_kwargs(dialect: str) -> dict:
    # Common kwargs.
    kwargs: dict = {"echo": False, "pool_pre_ping": True}
    if dialect == "postgres":
        # Sized for ~4 uvicorn workers each running up to a handful of concurrent
        # SSE streams + DB-backed read routes. Postgres default max_connections=100,
        # so 10 + 20 = 30 per worker × 4 workers = 120 peak — still fits a small
        # instance, and the pool_timeout prevents indefinite hangs.
        kwargs.update({
            "pool_size": 10,
            "max_overflow": 20,
            "pool_timeout": 30,
            "pool_recycle": 1800,  # recycle connections every 30 min to dodge
                                    # server-side idle kills
        })
    # SQLite doesn't respect pool_size; aiosqlite uses a single connection
    # under the hood. No extra tuning needed.
    return kwargs


engine = create_async_engine(_db_url, **_engine_kwargs(DB_DIALECT))
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables and add any missing columns. Called on app startup."""
    async with engine.begin() as conn:
        from db.models import Base  # noqa: F811
        await conn.run_sync(Base.metadata.create_all)

    await _migrate_columns()

    logger.info("Database tables initialized")


async def _migrate_columns() -> None:
    """
    Idempotent DDL migrations. Each statement runs in its own transaction
    because Postgres aborts the surrounding transaction on the first error
    (e.g. "column already exists"), and a single shared transaction would
    poison every subsequent statement with "current transaction is aborted."
    """
    column_migrations = [
        ("intelligence_memos", "user_id", "TEXT"),
        ("trades", "user_id", "TEXT"),
        ("portfolio_snapshots", "user_id", "TEXT"),
        ("factor_exposures", "user_id", "TEXT"),
        ("morning_reports", "user_id", "TEXT"),
    ]
    for table, column, col_type in column_migrations:
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                )
            logger.info(f"Migrated: added {table}.{column}")
        except Exception as e:
            logger.debug(f"Migration skip {table}.{column}: {e}")

    legacy_sentinel = "__legacy_null__"
    legacy_tables = [
        "intelligence_memos", "trades", "portfolio_snapshots",
        "factor_exposures", "morning_reports", "scan_findings",
        "scan_runs", "watchlist", "signal_scores",
    ]
    for table in legacy_tables:
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(f"UPDATE {table} SET user_id = :sentinel WHERE user_id IS NULL"),
                    {"sentinel": legacy_sentinel},
                )
        except Exception as e:
            logger.debug(f"Sentinel backfill skip {table}: {e}")

    composite_indexes = [
        ("ix_memos_user_created", "intelligence_memos", "user_id, created_at"),
        ("ix_trades_user_status", "trades", "user_id, status"),
        ("ix_trades_memo", "trades", "memo_id"),
        ("ix_signal_scores_user_date", "signal_scores", "user_id, signal_date"),
    ]
    for name, table, cols in composite_indexes:
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({cols})")
                )
            logger.debug(f"Index ensured: {name}")
        except Exception as e:
            logger.debug(f"Index skip {name}: {e}")


async def ping_db(timeout: float = 3.0) -> dict:
    """
    Probe database connectivity. Returns {ok, dialect, error?}.
    Used by the health check and startup validation.
    """
    import asyncio
    try:
        async def _probe():
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        await asyncio.wait_for(_probe(), timeout=timeout)
        return {"ok": True, "dialect": DB_DIALECT}
    except asyncio.TimeoutError:
        return {"ok": False, "dialect": DB_DIALECT, "error": f"timeout after {timeout}s"}
    except Exception as e:
        return {"ok": False, "dialect": DB_DIALECT, "error": str(e)}


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
