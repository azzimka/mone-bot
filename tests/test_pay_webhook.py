"""Tests for Google Wallet webhook receiver and /autopay token management."""

from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery, Message
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

with patch.dict("os.environ", {
    "TELEGRAM_BOT_TOKEN": "123456789:bot-test-token",
    "GROQ_API_KEY": "test-key",
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
}):
    from bot.handlers import autopay, callbacks
    from bot.services.pay_webhook import create_pay_webhook_app

from bot.database.repositories import UserRepository
from bot.database.schema import initialize_schema
from bot.models import Transaction, User
from bot.services.ai_parser import ParsedTransaction, ParsedTransactions


class PayWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await initialize_schema(self.engine)
        self.pool = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.pool.begin() as session:
            user = await UserRepository.set_language(session, 111, "ru")
            _, self.token = await UserRepository.get_or_create_pay_token(session, 111, "azim", "Azim")
            self.user_id = user.id
        callbacks.pending_transactions.clear()
        callbacks.processing_transactions.clear()

        self.fake_bot = MagicMock()
        self.fake_bot.send_message = AsyncMock()
        self.fake_parser = MagicMock()
        self.fake_parser.parse_payment_notification = AsyncMock(
            return_value=ParsedTransactions(
                transactions=[
                    ParsedTransaction(
                        type="expense",
                        amount=Decimal("45000"),
                        currency="UZS",
                        category="Еда",
                        description="Korzinka",
                    )
                ]
            )
        )
        app = create_pay_webhook_app(
            bot=self.fake_bot,
            session_pool=self.pool,
            ai_parser=self.fake_parser,
        )
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        callbacks.pending_transactions.clear()
        callbacks.processing_transactions.clear()
        await self.client.close()
        await self.engine.dispose()

    async def test_health_and_unauthorized_requests(self):
        resp = await self.client.get("/health")
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.json(), {"status": "ok"})

        unauth = await self.client.post("/webhook/google-pay", json={"title": "Korzinka", "text": "45 000 UZS"})
        self.assertEqual(unauth.status, 401)

        bad_token = await self.client.post(
            "/webhook/google-pay",
            headers={"Authorization": "Bearer wrong-token"},
            json={"title": "Korzinka", "text": "45 000 UZS"},
        )
        self.assertEqual(bad_token.status, 401)
        self.fake_bot.send_message.assert_not_awaited()

    async def test_google_wallet_notification_sends_confirmation_and_saves_on_confirm(self):
        resp = await self.client.post(
            "/webhook/google-pay",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"title": "Korzinka", "text": "Оплата 45 000 UZS • Карта •••• 1234"},
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(await resp.json(), {"status": "sent", "count": 1})

        self.fake_bot.send_message.assert_awaited_once()
        kwargs = self.fake_bot.send_message.call_args.kwargs
        self.assertEqual(kwargs["chat_id"], 111)
        self.assertIn("Google Wallet", kwargs["text"])
        self.assertIn("45 000 UZS", kwargs["text"])
        self.assertIn("Korzinka", kwargs["text"])

        buttons = kwargs["reply_markup"].inline_keyboard[0]
        self.assertEqual([b.text for b in buttons], ["✅ Верно", "❌ Отменить"])
        confirm_data = buttons[0].callback_data
        self.assertTrue(confirm_data.startswith("confirm:"))

        # Nothing is written to DB before user taps ✅ Верно
        async with self.pool() as session:
            before_count = (await session.execute(select(func.count()).select_from(Transaction))).scalar_one()
        self.assertEqual(before_count, 0)

        # User confirms -> expense is saved cleanly without balance/remainder text
        cb = MagicMock(spec=CallbackQuery)
        cb.from_user = SimpleNamespace(id=111, username="azim", first_name="Azim")
        cb.message = MagicMock(spec=Message)
        cb.message.edit_text = AsyncMock()
        cb.data = confirm_data
        cb.answer = AsyncMock()
        async with self.pool() as session:
            await callbacks.on_confirm_transaction(cb, session)
            saved = (await session.execute(select(Transaction))).scalar_one()
        self.assertEqual((saved.type, saved.amount, saved.currency, saved.category, saved.description),
                         ("expense", Decimal("45000"), "UZS", "Еда", "Korzinka"))
        edited = cb.message.edit_text.call_args.args[0]
        self.assertIn("45 000 UZS", edited)
        self.assertNotIn("Остаток", edited)

    async def test_duplicate_and_ignored_notifications(self):
        first = await self.client.post(
            "/webhook/google-pay",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"title": "Safia", "text": "Оплата 30 000 UZS"},
        )
        self.assertEqual(await first.json(), {"status": "sent", "count": 1})

        second = await self.client.post(
            "/webhook/google-pay",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"title": "Safia", "text": "Оплата 30 000 UZS"},
        )
        self.assertEqual(await second.json(), {"status": "duplicate"})
        self.assertEqual(self.fake_bot.send_message.await_count, 1)

        # Non-expense notification (e.g., declined payment) is ignored silently
        self.fake_parser.parse_payment_notification.return_value = ParsedTransactions(transactions=[])
        ignored = await self.client.post(
            "/webhook/google-pay",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"title": "Google Wallet", "text": "Оплата отклонена"},
        )
        self.assertEqual(await ignored.json(), {"status": "ignored"})
        self.assertEqual(self.fake_bot.send_message.await_count, 1)

    async def test_autopay_command_and_token_rotation(self):
        # Group chat is rejected
        group_msg = MagicMock(spec=Message)
        group_msg.chat = SimpleNamespace(id=-100, type="group")
        group_msg.from_user = SimpleNamespace(id=111, username="azim", first_name="Azim")
        group_msg.answer = AsyncMock()
        async with self.pool() as session:
            await autopay.cmd_autopay(group_msg, session)
        self.assertNotIn(self.token, group_msg.answer.call_args.args[0])

        # Private chat returns instructions with personal token
        msg = MagicMock(spec=Message)
        msg.chat = SimpleNamespace(id=111, type="private")
        msg.from_user = SimpleNamespace(id=111, username="azim", first_name="Azim")
        msg.answer = AsyncMock()
        async with self.pool() as session:
            await autopay.cmd_autopay(msg, session)
        text_out = msg.answer.call_args.args[0]
        self.assertIn(self.token, text_out)
        self.assertIn("/webhook/google-pay", text_out)

        # Rotate token -> old token immediately stops working
        cb = MagicMock(spec=CallbackQuery)
        cb.from_user = msg.from_user
        cb.message = msg
        cb.message.edit_text = AsyncMock()
        cb.data = "autopay:rotate"
        cb.answer = AsyncMock()
        async with self.pool() as session:
            await autopay.cb_rotate_autopay_token(cb, session)
            refreshed = await session.get(User, self.user_id)
        self.assertNotEqual(refreshed.pay_webhook_token, self.token)

        old_resp = await self.client.post(
            "/webhook/google-pay",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"title": "Test", "text": "10 000 UZS"},
        )
        self.assertEqual(old_resp.status, 401)
