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
        # No real Postgres — use SQLite for local dev
        logger.info("No Postgres configured, using SQLite for local development")
        return "sqlite+aiosqlite:///./alphaengine.db"
    return url


engine = create_async_engine(_get_url(), echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    """Create all tables. Called on app startup."""
    async with engine.begin() as conn:
        from db.models import Base  # noqa: F811
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialized")


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
