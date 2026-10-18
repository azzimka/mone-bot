"""Recovery and queued warnings must follow the owner's current ledger state."""
import unittest
from unittest.mock import AsyncMock

from sqlalchemy import func, select

import test_web_api
from bot.models import BudgetAlert, RestoreLog, Transaction
from bot.services.finance_worker import finance_tick


class RestoreAndAlertRegressionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_web_api.WebApiTests.asyncSetUp
    asyncTearDown = test_web_api.WebApiTests.asyncTearDown
    payload = test_web_api.WebApiTests.payload

    async def test_same_backup_repairs_later_deletion_without_duplicate_entries(self):
        backup = (await self.client.get('/api/backup')).json()
        first = await self.client.post('/api/backup/restore', json=backup)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()['restored'], 0)
        await self.client.delete(f'/api/transactions/{self.own_tx}')
        repair = await self.client.post('/api/backup/restore', json=backup)
        self.assertEqual(repair.status_code, 200, repair.text)
        self.assertEqual((repair.json()['restored'], repair.json()['skipped']), (1, 2))
        self.assertFalse(repair.json()['already_restored'])
        repeated = await self.client.post('/api/backup/restore', json=backup)
        self.assertTrue(repeated.json()['already_restored'])
        self.assertEqual(repeated.json()['restored'], 0)
        async with self.pool() as session:
            self.assertEqual((await session.execute(select(func.count()).select_from(Transaction).where(Transaction.user_id == self.user.id))).scalar_one(), 3)
            self.assertEqual((await session.execute(select(func.count()).select_from(RestoreLog).where(RestoreLog.user_id == self.user.id))).scalar_one(), 1)

    async def test_raised_budget_cancels_stale_warning_and_future_crossing_alerts(self):
        budget = {'month': '2026-10', 'category': 'Еда', 'currency': 'UZS', 'amount': '30', 'notify_telegram': False}
        self.assertEqual((await self.client.post('/api/budgets', json=budget)).status_code, 201)
        raised = await self.client.post('/api/budgets', json={**budget, 'amount': '1000', 'notify_telegram': True})
        self.assertEqual(raised.status_code, 201)
        bot = AsyncMock()
        await finance_tick(self.pool, bot)
        bot.send_message.assert_not_awaited()
        async with self.pool() as session:
            self.assertEqual((await session.execute(select(func.count()).select_from(BudgetAlert))).scalar_one(), 0)
        self.assertEqual((await self.client.post('/api/transactions', json=self.payload(category='Еда', amount='800'))).status_code, 201)
        await finance_tick(self.pool, bot)
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertIn('80%', bot.send_message.call_args.args[1])
        await finance_tick(self.pool, bot)
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_deleted_expense_invalidates_pending_budget_warning(self):
        budget = {'month': '2026-10', 'category': 'Еда', 'currency': 'UZS', 'amount': '30', 'notify_telegram': False}
        await self.client.post('/api/budgets', json=budget)
        await self.client.delete(f'/api/transactions/{self.own_tx}')
        await self.client.post('/api/budgets', json={**budget, 'notify_telegram': True})
        bot = AsyncMock()
        await finance_tick(self.pool, bot)
        bot.send_message.assert_not_awaited()
