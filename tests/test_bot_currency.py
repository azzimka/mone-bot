"""Bot expense-only ledger regressions: exact money, owned confirmation and no balance/income flows."""
import asyncio
import json
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery, Message
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Handler imports need configuration but these tests never contact external APIs.
with patch.dict("os.environ", {
    "TELEGRAM_BOT_TOKEN": "123456789:bot-test-token", "GROQ_API_KEY": "test-key",
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
}):
    from bot.handlers import callbacks, commands, text, voice
from bot.database.repositories import TransactionRepository
from bot.models import Account, Base, Transaction, User
from bot.services.ai_parser import AIParser, ParsedTransaction, ParsedTransactions
from bot.services.amounts import AmountParseError, parse_amount
from bot.services.reports import ReportService


class BotCurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.pool = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = self.pool()
        self.user = User(telegram_id=111, language="uz", default_currency="UZS", timezone="Pacific/Honolulu")
        self.other = User(telegram_id=222, language="ru", default_currency="UZS")
        self.session.add_all([self.user, self.other])
        await self.session.flush()
        self.cash = Account(user_id=self.user.id, name="Cash", kind="cash", currency="UZS")
        self.usd = Account(user_id=self.user.id, name="Dollars", kind="cash", currency="USD")
        self.session.add_all([self.cash, self.usd])
        await self.session.flush()
        self.session.add(
            Transaction(user_id=self.user.id, account_id=self.cash.id, type="expense", amount=Decimal("25.25"), currency="UZS", category="Еда", date=date(2026, 10, 1))
        )
        await self.session.commit()
        callbacks.pending_transactions.clear()
        callbacks.processing_transactions.clear()

    async def asyncTearDown(self):
        callbacks.pending_transactions.clear()
        callbacks.processing_transactions.clear()
        await self.session.close()
        await self.engine.dispose()

    def message(self, content="Coffee", user_id=111):
        message = MagicMock(spec=Message)
        message.from_user = SimpleNamespace(id=user_id, username="test", first_name="Test")
        message.chat = SimpleNamespace(id=user_id, type="private")
        message.text = content
        message.answer = AsyncMock()
        message.reply = AsyncMock()
        message.edit_text = AsyncMock()
        return message

    def callback(self, action="confirm", key="entry", user_id=111):
        callback = MagicMock(spec=CallbackQuery)
        callback.message = self.message(user_id=user_id)
        callback.from_user = callback.message.from_user
        callback.data = f"{action}:{key}"
        callback.answer = AsyncMock()
        return callback

    def pending(self, **overrides):
        callbacks.pending_transactions["entry"] = {
            "user_id": self.user.id,
            "transaction": {"type": "expense", "amount": Decimal("20.50"), "currency": "USD", "category": "Еда", "description": "Coffee", **overrides},
        }

    async def test_expense_confirmation_saves_without_balance_or_remainder(self):
        self.pending()
        callback = self.callback()
        with patch("bot.handlers.callbacks.local_today", return_value=date(2026, 9, 30)):
            await callbacks.on_confirm_transaction(callback, self.session)
        result = callback.message.edit_text.call_args.args[0]
        self.assertIn("20.5 USD", result)
        for forbidden in ("Остаток", "Qoldiq", "Баланс", "Balans", "UZS"):
            self.assertNotIn(forbidden, result)
        record = (await self.session.execute(select(Transaction).where(Transaction.description == "Coffee"))).scalar_one()
        self.assertEqual((record.amount, record.currency, record.account_id, record.date), (Decimal("20.50"), "USD", self.usd.id, date(2026, 9, 30)))
        self.assertNotIn("entry", callbacks.pending_transactions)

    async def test_income_and_reconcile_are_rejected_everywhere(self):
        for kind in ("income", "reconcile"):
            with self.subTest(kind=kind):
                with self.assertRaises(ValidationError):
                    ParsedTransaction(type=kind, amount=Decimal("100"), category="Другое", description="test")
                with self.assertRaises(ValueError):
                    await TransactionRepository.create(self.session, self.user.id, kind, Decimal("100"))
                self.pending(type=kind, amount=Decimal("100"), currency="UZS")
                cb = self.callback()
                await callbacks.on_confirm_transaction(cb, self.session)
                cb.message.edit_text.assert_not_awaited()
        self.assertEqual((await self.session.execute(select(func.count()).select_from(Transaction))).scalar_one(), 1)

    async def test_foreign_user_cannot_confirm_or_cancel_pending_entry(self):
        self.pending()
        callback = self.callback(user_id=222)
        await callbacks.on_confirm_transaction(callback, self.session)
        await callbacks.on_cancel_transaction(self.callback("cancel", user_id=222), self.session)
        self.assertIn("entry", callbacks.pending_transactions)
        callback.message.edit_text.assert_not_awaited()
        self.assertEqual((await self.session.execute(select(func.count()).select_from(Transaction))).scalar_one(), 1)

    async def test_two_simultaneous_confirmation_clicks_save_only_once(self):
        self.pending()
        entered, release = asyncio.Event(), asyncio.Event()
        original = TransactionRepository.create

        async def slow_create(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        with patch.object(TransactionRepository, "create", side_effect=slow_create):
            first = asyncio.create_task(callbacks.on_confirm_transaction(self.callback(), self.session))
            await entered.wait()
            await callbacks.on_confirm_transaction(self.callback(), self.session)
            release.set()
            await first
        self.assertEqual((await self.session.execute(select(func.count()).select_from(Transaction).where(Transaction.description == "Coffee"))).scalar_one(), 1)

    async def test_commit_failure_keeps_pending_and_retry_saves_exactly_once(self):
        owner_id = (await self.session.execute(select(User.id).where(User.telegram_id == 111))).scalar_one()
        callbacks.pending_transactions["entry"] = {"user_id": owner_id, "transaction": {
            "type": "expense", "amount": Decimal("12.35"), "currency": "USD", "category": "Еда", "description": "Commit retry",
        }}
        callback = self.callback()
        with patch.object(self.session, "commit", AsyncMock(side_effect=RuntimeError("injected commit failure"))):
            await callbacks.on_confirm_transaction(callback, self.session)
        callback.message.edit_text.assert_not_awaited()
        self.assertIn("entry", callbacks.pending_transactions)
        self.assertNotIn("entry", callbacks.processing_transactions)
        self.assertEqual((await self.session.execute(select(func.count()).select_from(Transaction).where(Transaction.description == "Commit retry"))).scalar_one(), 0)
        before = (await self.session.execute(select(func.count()).select_from(Transaction))).scalar_one()
        await callbacks.on_confirm_transaction(self.callback(), self.session)
        self.assertNotIn("entry", callbacks.pending_transactions)
        self.assertEqual((await self.session.execute(select(func.count()).select_from(Transaction))).scalar_one(), before + 1)

    async def test_failed_telegram_delivery_does_not_allow_duplicate_committed_entry(self):
        self.pending()
        callback = self.callback()
        callback.message.edit_text.side_effect = RuntimeError("Telegram unavailable")
        with self.assertRaises(RuntimeError):
            await callbacks.on_confirm_transaction(callback, self.session)
        await self.session.rollback()  # Mirror middleware handling delivery errors.
        self.assertNotIn("entry", callbacks.pending_transactions)
        await callbacks.on_confirm_transaction(self.callback(), self.session)
        self.assertEqual((await self.session.execute(select(func.count()).select_from(Transaction).where(Transaction.description == "Coffee"))).scalar_one(), 1)

    async def test_text_and_voice_use_saved_default_but_preserve_explicit_currency(self):
        self.user.default_currency = "USD"
        await self.session.flush()
        parsed = ParsedTransactions(transactions=[ParsedTransaction(type="expense", amount="12.35", currency="EUR", category="Еда", description="Coffee")])
        parser = AsyncMock(return_value=parsed)
        preview_message = self.message("Coffee 12.35 EUR")
        with patch.object(text.ai_parser, "parse", parser):
            await text.handle_text_message(preview_message, self.session)
        parser.assert_awaited_once_with("Coffee 12.35 EUR", "USD")
        self.assertIn("12.35 EUR", preview_message.answer.call_args.args[0])

        self.assertEqual(next(iter(callbacks.pending_transactions.values()))["transaction"]["currency"], "EUR")
        bot = AsyncMock()
        bot.get_file.return_value = SimpleNamespace(file_path="voice.ogg")
        message = self.message()
        message.voice = SimpleNamespace(file_id="test-file")
        parser = AsyncMock(return_value=parsed)
        with patch.object(voice.ai_parser, "parse", parser), patch.object(voice.speech_service, "transcribe", AsyncMock(return_value="Coffee 12.35 EUR")):
            await voice.handle_voice_message(message, bot, self.session)
        parser.assert_awaited_once_with("Coffee 12.35 EUR", "USD")

    async def test_invalid_amounts_never_create_ledger_rows(self):
        for amount in ("-1", "0", "NaN", "1.001", "10000000000000"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                await TransactionRepository.create(self.session, self.user.id, "expense", amount)
        self.assertEqual((await self.session.execute(select(func.count()).select_from(Transaction))).scalar_one(), 1)

    def test_amount_parsing_formatting_and_expense_only_reports(self):
        self.assertEqual(parse_amount("12.50"), Decimal("12.50"))
        self.assertEqual(parse_amount("1 234,56"), Decimal("1234.56"))
        for bad in ("1,000", "1.001", "abc", ""):
            with self.assertRaises(AmountParseError):
                parse_amount(bad)
        self.assertEqual(commands.fmt(Decimal("9999999999999.99"), "USD"), "9 999 999 999 999.99 USD")
        reports = ReportService()
        daily = reports.format_daily_report([{"type": "expense", "category": "Еда", "description": "Кофе", "amount": 25000}], 25000, "UZS")
        period = reports.format_period_report({"Еда": 25000}, 25000, "Ноябрь", "UZS")
        for text_out in (daily, period):
            for forbidden in ("Доход", "доход", "Остаток", "Баланс"):
                self.assertNotIn(forbidden, text_out)

    def test_parser_uses_default_for_omitted_currency_and_logs_no_financial_content(self):
        parser = AIParser.__new__(AIParser)
        parser.model = "test-model"
        secret = "PRIVATE_EXPENSE_12225"
        response = {"transactions": [{"type": "expense", "amount": 12.35, "category": "Еда", "description": secret}]}
        create = MagicMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response)))]))
        parser.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with self.assertLogs("bot.services.ai_parser", level="DEBUG") as logs:
            parsed = parser._parse_sync(secret, "USD")
        self.assertEqual((parsed.transactions[0].currency, parsed.transactions[0].amount), ("USD", Decimal("12.35")))
        self.assertNotIn(secret, " ".join(logs.output))
        create.return_value.choices[0].message.content = json.dumps({"transactions": [{**response["transactions"][0], "amount": -1}]})
        with self.assertLogs("bot.services.ai_parser", level="ERROR") as logs, self.assertRaises(ValidationError):
            parser._parse_sync(secret, "USD")
        self.assertNotIn(secret, " ".join(logs.output))
        for invalid in ("-1", "0", "NaN", "Infinity", "1.001"):
            with self.subTest(amount=invalid), self.assertRaises(ValidationError):
                ParsedTransaction(type="expense", amount=invalid, category="Еда", description="test")
