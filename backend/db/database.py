"""
Database connection layer — async SQLAlchemy with asyncpg for Postgres.

For local dev without Postgres, falls back to SQLite (aiosqlite).
Railway provides DATABASE_URL automatically when you add the Postgres plugin.
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
import logging

from config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _get_url() -> str:
    """Resolve the database URL, falling back to SQLite for local dev."""
    url = settings.DATABASE_URL
    if not url or url.startswith("postgresql+asyncpg://postgres:postgres@localhost"):
        logger.info("No Postgres configured, using SQLite for local development")
        return "sqlite+aiosqlite:///./alphaengine.db"
    # Railway provides postgresql:// — convert to postgresql+asyncpg:// for async driver
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(_get_url(), echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    """Create all tables and add any missing columns. Called on app startup."""
    async with engine.begin() as conn:
        from db.models import Base  # noqa: F811
        await conn.run_sync(Base.metadata.create_all)

    # Migrate missing columns for SQLite (create_all doesn't alter existing tables)
    url = _get_url()
    if "sqlite" in url:
        await _migrate_sqlite()

    logger.info("Database tables initialized")


async def _migrate_sqlite():
    """Add missing columns to existing SQLite tables."""
    migrations = [
        ("intelligence_memos", "user_id", "TEXT"),
        ("trades", "user_id", "TEXT"),
    ]
    async with engine.begin() as conn:
        for table, column, col_type in migrations:
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                    )
                )
                logger.info(f"Added column {table}.{column}")
            except Exception:
                # Column already exists — ignore
                pass


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
