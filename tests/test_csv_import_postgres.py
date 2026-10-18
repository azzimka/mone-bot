"""Optional real-PostgreSQL concurrency tests, isolated in a temporary schema.

Set CSV_TEST_POSTGRES_URL to a PostgreSQL SQLAlchemy asyncpg URL to enable.
The database user must be able to create schemas. No existing schema is modified.
"""

import asyncio
import os
import unittest
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from bot.database.csv_imports import finish_import, stage_import
from bot.models import Base, CsvImport, Transaction, User
from bot.services.csv_import import CsvImportError, parse_csv

DATA = b"date,type,amount\n2025-01-01,income,1000\n2025-01-02,expense,25.50\n"


@unittest.skipUnless(os.getenv("CSV_TEST_POSTGRES_URL"), "Set CSV_TEST_POSTGRES_URL for PostgreSQL concurrency tests")
class CsvPostgresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = "csv_test_" + uuid.uuid4().hex
        self.engine = create_async_engine(os.environ["CSV_TEST_POSTGRES_URL"])
        async with self.engine.begin() as conn:
            await conn.execute(CreateSchema(self.schema))
        mapped = self.engine.execution_options(schema_translate_map={None: self.schema})
        async with mapped.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.pool = async_sessionmaker(mapped, expire_on_commit=False)
        async with self.pool.begin() as session:
            user = User(telegram_id=123, default_currency="UZS")
            session.add(user)
            await session.flush()
            self.user_id = user.id

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            await conn.execute(DropSchema(self.schema, cascade=True))
        await self.engine.dispose()

    async def stage(self):
        async with self.pool.begin() as session:
            item = await stage_import(session, self.user_id, "export.csv", DATA, parse_csv(DATA))
            return item.id

    async def finish(self, import_id, cancel=False):
        async with self.pool.begin() as session:
            return await finish_import(session, import_id, 123, cancel=cancel)

    async def test_simultaneous_confirms_insert_only_once(self):
        import_id = await self.stage()
        results = await asyncio.gather(self.finish(import_id), self.finish(import_id), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, CsvImportError) for r in results), 1)
        self.assertIn(2, results)
        async with self.pool() as session:
            count = (await session.execute(select(func.count()).select_from(Transaction))).scalar_one()
            self.assertEqual(count, 2)

    async def test_simultaneous_uploads_share_one_staged_import(self):
        ids = await asyncio.gather(self.stage(), self.stage())
        self.assertEqual(ids[0], ids[1])
        async with self.pool() as session:
            count = (await session.execute(select(func.count()).select_from(CsvImport))).scalar_one()
            self.assertEqual(count, 1)

    async def test_cancel_and_confirm_cannot_both_succeed(self):
        import_id = await self.stage()
        results = await asyncio.gather(self.finish(import_id), self.finish(import_id, cancel=True), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, CsvImportError) for r in results), 1)
        async with self.pool() as session:
            item = await session.get(CsvImport, import_id)
            count = (await session.execute(select(func.count()).select_from(Transaction))).scalar_one()
            self.assertEqual(count, 2 if item.status == "complete" else 0)
