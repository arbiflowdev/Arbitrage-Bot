"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import settings


def _build_engine() -> AsyncEngine:
    """Build the async engine, adjusting pool/SSL args by dialect."""
    url = settings.normalized_database_url
    is_sqlite = url.startswith("sqlite")

    kwargs: dict = {
        "echo": settings.DB_ECHO,
        "future": True,
    }
    if is_sqlite:
        # SQLite uses a single connection / single thread in tests.
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_size"] = settings.DB_POOL_SIZE
        kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
        kwargs["pool_pre_ping"] = True
        connect_args = settings.db_connect_args
        if connect_args:
            kwargs["connect_args"] = connect_args

    return create_async_engine(url, **kwargs)


engine: AsyncEngine = _build_engine()

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a transactional async session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose pooled connections (call on application shutdown)."""
    await engine.dispose()
