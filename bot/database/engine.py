"""Database engine and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Import all models to ensure metadata registration
import bot.models  # noqa: F401
from bot.config import settings
from bot.database.schema import initialize_schema

_engine_kwargs: dict = {
    "echo": False,
    "future": True,
}
if not settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs.update(
        pool_size=20,
        max_overflow=30,
        pool_timeout=15,
        pool_recycle=1800,
        pool_pre_ping=True,
    )

engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    **_engine_kwargs,
)

async_session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an asynchronous transactional database session scope.

    Yields:
        AsyncSession: Active SQLAlchemy async session.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Initialize database tables using Base.metadata."""
    await initialize_schema(engine)
