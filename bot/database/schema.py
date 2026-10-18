"""Serialize bot/API startup when both create newly introduced tables."""

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from bot.models import Base


async def initialize_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.execute(text("SELECT pg_advisory_xact_lock(73706101)"))
        await conn.run_sync(Base.metadata.create_all)
        columns = await conn.run_sync(lambda sync: {column['name'] for column in inspect(sync).get_columns('users')})
        if 'language' not in columns:
            await conn.execute(text("ALTER TABLE users ADD COLUMN language VARCHAR(2) CHECK (language IN ('uz', 'ru'))"))
        category_columns = await conn.run_sync(lambda sync: {column['name'] for column in inspect(sync).get_columns('categories')})
        for name in ('display_name', 'parent_name'):
            if name not in category_columns:
                await conn.execute(text(f"ALTER TABLE categories ADD COLUMN {name} VARCHAR(100)"))
