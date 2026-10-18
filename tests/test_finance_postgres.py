"""Real PostgreSQL owner-lock checks; all writes stay in a disposable schema."""
import asyncio
import os
import unittest
from datetime import date
from decimal import Decimal
from sqlalchemy import select, func
import test_csv_import_postgres as pg_tests
from bot.models import Account, Transaction, User, RecurringRule
from bot.services.finance import ensure_accounts, recurring_due
from bot.services.web_import import preview_csv
from bot.database.csv_imports import finish_import
from api.finance_schemas import CsvPreviewInput


@unittest.skipUnless(os.getenv('CSV_TEST_POSTGRES_URL'), 'Set CSV_TEST_POSTGRES_URL for PostgreSQL concurrency tests')
class FinancePostgresTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=pg_tests.CsvPostgresTests.asyncSetUp
    asyncTearDown=pg_tests.CsvPostgresTests.asyncTearDown

    async def test_first_account_is_created_once_for_parallel_requests(self):
        async def initialize():
            async with self.pool.begin() as session:
                user=await session.get(User,self.user_id)
                return [item.id for item in await ensure_accounts(session,user)]
        results=await asyncio.gather(initialize(),initialize(),initialize())
        self.assertEqual(results[0],results[1])
        self.assertEqual(results[1],results[2])
        async with self.pool() as session:
            self.assertEqual((await session.execute(select(func.count()).select_from(Account))).scalar_one(),1)

    async def test_overlapping_recurring_workers_insert_only_once(self):
        async with self.pool.begin() as session:
            user=await session.get(User,self.user_id)
            account=(await ensure_accounts(session,user))[0]
            session.add(RecurringRule(user_id=user.id,account_id=account.id,type='expense',amount=Decimal('10'),category='Еда',frequency='daily',next_date=date(2026,10,19),anchor_day=19))
        async def tick():
            async with self.pool.begin() as session:
                user=await session.get(User,self.user_id)
                await ensure_accounts(session,user)
                return await recurring_due(session,user,date(2026,10,19))
        results=await asyncio.gather(tick(),tick())
        self.assertEqual(sorted(results),[0,1])
        async with self.pool() as session:
            self.assertEqual((await session.execute(select(func.count()).select_from(Transaction))).scalar_one(),1)

    async def test_overlapping_csv_files_recheck_duplicates_at_confirmation(self):
        async with self.pool.begin() as session:
            user=await session.get(User,self.user_id)
            account=(await ensure_accounts(session,user))[0]
            imports=[]
            for content in ['date,type,amount\n2026-10-19,expense,10\n2026-10-19,income,20\n','date,type,amount\n2026-10-19,expense,10\n2026-10-19,income,30\n']:
                body=CsvPreviewInput(content=content,account_id=account.id,mapping={'date':'date','type':'type','amount':'amount'})
                imports.append((await preview_csv(session,user,body,account))['id'])
        async def confirm(key):
            async with self.pool.begin() as session:
                return await finish_import(session,key,123)
        self.assertEqual(sum(await asyncio.gather(*(confirm(key) for key in imports))),3)
        async with self.pool() as session:
            self.assertEqual((await session.execute(select(func.count()).select_from(Transaction))).scalar_one(),3)
