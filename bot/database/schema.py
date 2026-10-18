"""Serialize bot/API startup when both create newly introduced tables."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.models import Base


async def initialize_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(73706101)"))
        await conn.run_sync(Base.metadata.create_all)
