"""Database initialization and async session management."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings
from .models import Base

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False}
    if "sqlite" in settings.database_url
    else {},
)

async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def init_db() -> None:
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """Yield an async session (use as an async context manager)."""
    async with async_session_factory() as session:
        yield session  # type: ignore[misc]


async def close_db() -> None:
    """Dispose of the engine connection pool."""
    await engine.dispose()
