"""Run with aiosqlite installed; production uses PostgreSQL row locks."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.database.csv_imports import finish_import, stage_import
from bot.handlers.csv_import import confirm_csv, upload_csv
from bot.models import Base, CsvImport, Transaction, User
from bot.services.csv_import import CsvImportError, parse_csv

DATA = b"date,type,amount,description\n2025-01-10,income,1000,Salary\n2025-01-11,expense,25.50,Coffee\n"


class CsvDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.pool = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = self.pool()
        self.user = User(telegram_id=123, default_currency="UZS")
        self.session.add(self.user)
        await self.session.commit()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def stage(self):
        item = await stage_import(self.session, self.user.id, "export.csv", DATA, parse_csv(DATA))
        await self.session.commit()
        return item

    async def count(self):
        return (await self.session.execute(select(func.count()).select_from(Transaction))).scalar_one()

    def callback(self, import_id, telegram_id=123, action="confirm"):
        return SimpleNamespace(data=f"csv:{action}:{import_id}", from_user=SimpleNamespace(id=telegram_id),
                               answer=AsyncMock(), message=SimpleNamespace(
                                   chat=SimpleNamespace(type="private"), answer=AsyncMock(), edit_text=AsyncMock()))

    async def test_staging_persists_original_without_creating_transactions(self):
        item = await self.stage()
        self.assertEqual(item.source_text, DATA.decode())
        self.assertEqual(await self.count(), 0)
        async with self.pool() as other_session:
            saved = await other_session.get(CsvImport, item.id)
            self.assertEqual(saved.status, "pending")

    async def test_confirm_preserves_dates_decimals_and_categories(self):
        item = await self.stage()
        self.assertEqual(await finish_import(self.session, item.id, 123), 2)
        await self.session.commit()
        rows = (await self.session.execute(select(Transaction).order_by(Transaction.date))).scalars().all()
        self.assertEqual(rows[1].amount, Decimal("25.50"))
        self.assertEqual(rows[1].date.isoformat(), "2025-01-11")
        self.assertEqual(rows[1].category, "Еда")
        self.assertEqual(item.status, "complete")

    async def test_other_users_cannot_confirm_or_cancel(self):
        item = await self.stage()
        for cancel in (False, True):
            with self.assertRaises(CsvImportError):
                await finish_import(self.session, item.id, 999, cancel=cancel)
        self.assertEqual(await self.count(), 0)
        self.assertEqual(item.status, "pending")

    async def test_repeated_confirm_and_upload_do_not_duplicate_rows(self):
        item = await self.stage()
        await finish_import(self.session, item.id, 123)
        await self.session.commit()
        with self.assertRaises(CsvImportError):
            await finish_import(self.session, item.id, 123)
        with self.assertRaises(CsvImportError):
            await stage_import(self.session, self.user.id, "renamed.csv", DATA, parse_csv(DATA))
        self.assertEqual(await self.count(), 2)

    async def test_same_file_can_be_imported_by_different_users(self):
        await self.stage()
        other = User(telegram_id=456)
        self.session.add(other)
        await self.session.flush()
        item = await stage_import(self.session, other.id, "export.csv", DATA, parse_csv(DATA))
        self.assertEqual(await finish_import(self.session, item.id, 456), 2)

    async def test_cancel_and_reupload(self):
        item = await self.stage()
        await finish_import(self.session, item.id, 123, cancel=True)
        await self.session.commit()
        with self.assertRaises(CsvImportError):
            await finish_import(self.session, item.id, 123)
        self.assertEqual(await self.count(), 0)
        await self.stage()
        self.assertEqual(await finish_import(self.session, item.id, 123), 2)

    async def test_expired_confirmation(self):
        item = await self.stage()
        item.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await self.session.commit()
        with self.assertRaises(CsvImportError):
            await finish_import(self.session, item.id, 123)
        self.assertEqual(await self.count(), 0)

    async def test_rollback_restores_pending_and_removes_all_inserted_rows(self):
        item = await self.stage()
        import_id = item.id
        await finish_import(self.session, import_id, 123)
        await self.session.rollback()
        self.assertEqual(await self.count(), 0)
        self.assertEqual((await self.session.get(CsvImport, import_id)).status, "pending")

    async def test_handler_commits_before_success_message(self):
        item = await self.stage()
        callback = self.callback(item.id)
        async def check_committed(*args, **kwargs):
            self.assertFalse(self.session.in_transaction())
            async with self.pool() as check:
                self.assertEqual((await check.get(CsvImport, item.id)).status, "complete")
        callback.message.edit_text.side_effect = check_committed
        await confirm_csv(callback, self.session)
        callback.message.edit_text.assert_awaited_once()

    async def test_handler_commit_failure_does_not_claim_success(self):
        item = await self.stage()
        import_id = item.id
        callback = self.callback(import_id)
        original_commit = self.session.commit
        self.session.commit = AsyncMock(side_effect=RuntimeError("simulated commit failure"))
        await confirm_csv(callback, self.session)
        self.session.commit = original_commit
        callback.message.edit_text.assert_not_awaited()
        self.assertEqual(await self.count(), 0)
        self.assertEqual((await self.session.get(CsvImport, import_id)).status, "pending")

    async def test_upload_routes_document_to_persisted_preview(self):
        message = SimpleNamespace(chat=SimpleNamespace(type="private"),
                                  from_user=SimpleNamespace(id=123, username=None, first_name=None),
                                  document=SimpleNamespace(file_name="export.csv", file_size=len(DATA)),
                                  answer=AsyncMock())
        async def download(document, destination):
            destination.write(DATA)
        await upload_csv(message, SimpleNamespace(download=download), self.session)
        keyboard = message.answer.await_args.kwargs["reply_markup"]
        self.assertTrue(keyboard.inline_keyboard[0][0].callback_data.startswith("csv:confirm:"))
        self.assertEqual(await self.count(), 0)
        self.assertEqual((await self.session.execute(select(func.count()).select_from(CsvImport))).scalar_one(), 1)


if __name__ == "__main__":
    unittest.main()
