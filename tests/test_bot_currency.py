"""Bot ledger regressions: exact money, owned confirmation and scoped balances."""
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
    from bot.handlers import balance, callbacks, commands, text, voice
from bot.database.repositories import TransactionRepository
from bot.models import Account, Base, Transaction, Transfer, User
from bot.services.ai_parser import AIParser, ParsedTransaction, ParsedTransactions
from bot.services.finance import account_balances, balance_totals


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
        self.cash = Account(user_id=self.user.id, name="Cash", kind="cash", currency="UZS", opening_balance=Decimal("100"))
        self.card = Account(user_id=self.user.id, name="Card", kind="card", currency="UZS", opening_balance=Decimal("500"))
        self.usd = Account(user_id=self.user.id, name="Dollars", kind="cash", currency="USD", opening_balance=Decimal("10"))
        self.session.add_all([self.cash, self.card, self.usd])
        await self.session.flush()
        self.session.add_all([
            Transaction(user_id=self.user.id, account_id=self.cash.id, type="income", amount=Decimal("1000"), currency="UZS", category="Зарплата", date=date(2026, 10, 1)),
            Transaction(user_id=self.user.id, account_id=self.cash.id, type="expense", amount=Decimal("25.25"), currency="UZS", category="Еда", date=date(2026, 10, 1)),
            Transaction(user_id=self.user.id, account_id=self.usd.id, type="income", amount=Decimal("100"), currency="USD", category="Зарплата", date=date(2026, 10, 1)),
            Transfer(user_id=self.user.id, source_id=self.cash.id, destination_id=self.card.id, source_amount=Decimal("200"), destination_amount=Decimal("200"), date=date(2026, 10, 1), request_key="initial-card-transfer"),
        ])
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

    def state(self, **overrides):
        data = {"user_id": self.user.id, "account_id": self.cash.id, "currency": "UZS", **overrides}
        state = SimpleNamespace(get_data=AsyncMock(return_value=data), clear=AsyncMock(), update_data=AsyncMock(), set_state=AsyncMock())
        return state

    async def test_expense_confirmation_uses_its_currency_and_opening_balance(self):
        self.pending()
        callback = self.callback()
        with patch("bot.handlers.callbacks.local_today", return_value=date(2026, 9, 30)):
            await callbacks.on_confirm_transaction(callback, self.session)
        result = callback.message.edit_text.call_args.args[0]
        self.assertIn("89.5 USD", result)
        self.assertNotIn("UZS", result)
        record = (await self.session.execute(select(Transaction).where(Transaction.description == "Coffee"))).scalar_one()
        self.assertEqual((record.amount, record.currency, record.account_id, record.date), (Decimal("20.50"), "USD", self.usd.id, date(2026, 9, 30)))
        self.assertNotIn("entry", callbacks.pending_transactions)

    async def test_reconcile_changes_only_chosen_account_and_preserves_cents(self):
        before = await account_balances(self.session, self.user)
        self.pending(type="reconcile", amount=Decimal("900.50"), currency="UZS", account_id=self.cash.id)
        await callbacks.on_confirm_transaction(self.callback(), self.session)
        after = await account_balances(self.session, self.user)
        values = {item["id"]: Decimal(item["balance"]) for item in after}
        self.assertEqual(values[self.cash.id], Decimal("900.50"))
        self.assertEqual(values[self.card.id], Decimal("700"))
        self.assertEqual(values[self.usd.id], Decimal("110"))
        correction = (await self.session.execute(select(Transaction).where(Transaction.category == "Сверка"))).scalar_one()
        self.assertEqual((correction.amount, correction.type, correction.account_id), (Decimal("25.75"), "income", self.cash.id))
        self.assertEqual(Decimal(next(item for item in before if item['id'] == self.cash.id)['balance']), Decimal('874.75'))

    async def test_foreign_user_cannot_confirm_or_cancel_pending_entry(self):
        self.pending()
        callback = self.callback(user_id=222)
        await callbacks.on_confirm_transaction(callback, self.session)
        await callbacks.on_cancel_transaction(self.callback("cancel", user_id=222), self.session)
        self.assertIn("entry", callbacks.pending_transactions)
        callback.message.edit_text.assert_not_awaited()
        self.assertEqual((await self.session.execute(select(func.count()).select_from(Transaction))).scalar_one(), 3)

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
        for kind in ("expense", "reconcile"):
            with self.subTest(kind=kind):
                # Keep an independent pending UUID for each flow; rollback expires
                # ORM instances, so retrieve the owner again on the next loop.
                owner_id = (await self.session.execute(select(User.id).where(User.telegram_id == 111))).scalar_one()
                callbacks.pending_transactions["entry"] = {"user_id": owner_id, "transaction": {
                    "type": kind, "amount": Decimal("12.35"), "currency": "USD", "category": "Еда", "description": "Commit retry " + kind,
                }}
                callback = self.callback()
                with patch.object(self.session, "commit", AsyncMock(side_effect=RuntimeError("injected commit failure"))):
                    await callbacks.on_confirm_transaction(callback, self.session)
                callback.message.edit_text.assert_not_awaited()
                self.assertIn("entry", callbacks.pending_transactions)
                self.assertNotIn("entry", callbacks.processing_transactions)
                self.assertEqual((await self.session.execute(select(func.count()).select_from(Transaction).where(Transaction.description == "Commit retry " + kind))).scalar_one(), 0)
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

        self.assertEqual(next(iter(callbacks.pending_transactions.values()))['transaction']['currency'], 'EUR')
        bot = AsyncMock()
        bot.get_file.return_value = SimpleNamespace(file_path="voice.ogg")
        message = self.message()
        message.voice = SimpleNamespace(file_id="test-file")
        parser = AsyncMock(return_value=parsed)
        with patch.object(voice.ai_parser, "parse", parser), patch.object(voice.speech_service, "transcribe", AsyncMock(return_value="Coffee 12.35 EUR")):
            await voice.handle_voice_message(message, bot, self.session)
        parser.assert_awaited_once_with("Coffee 12.35 EUR", "USD")

    async def test_multiple_account_reconciliation_never_creates_a_pending_entry(self):
        parsed = ParsedTransactions(needs_account_selection=True, transactions=[ParsedTransaction(type='reconcile', amount='300', currency='USD', category='Сверка', description='Two cards')])
        self.assertEqual(parsed.transactions, [])
        message = self.message('On one card 100 USD, on another 200 USD')
        with patch.object(text.ai_parser, 'parse', AsyncMock(return_value=parsed)):
            await text.handle_text_message(message, self.session)
        self.assertEqual(callbacks.pending_transactions, {})
        message.answer.assert_awaited_once()

    async def test_fsm_reconcile_keeps_initial_account_currency_after_preferences_change(self):
        state = self.state()
        self.user.default_currency = "USD"
        await self.session.flush()
        await balance._apply_reconciliation(self.message(), self.session, state, Decimal("900.50"))
        cash = await balance_totals(self.session, self.user, "UZS", self.cash.id)
        usd = await balance_totals(self.session, self.user, "USD", self.usd.id)
        self.assertEqual(cash['balance'], Decimal('900.50'))
        self.assertEqual(usd['balance'], Decimal('110'))
        state.clear.assert_awaited_once()

    async def test_invalid_amounts_never_create_ledger_rows(self):
        for amount in ("-1", "0", "NaN", "1.001", "10000000000000"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                await TransactionRepository.create(self.session, self.user.id, "expense", amount)
        self.assertEqual((await self.session.execute(select(func.count()).select_from(Transaction))).scalar_one(), 3)

    async def test_balance_command_and_button_report_same_current_balance(self):
        message = self.message("/balance")
        await commands.cmd_balance(message, self.session)
        report = message.answer.call_args.args[0]
        self.assertIn("1 574.75 UZS", report)
        self.assertNotIn("USD", report)

    async def test_topup_decimal_input_is_not_multiplied_by_removing_period(self):
        state = self.state(currency="USD", account_id=self.usd.id)
        message = self.message("12.50")
        await balance.fsm_topup_amount(message, state)
        state.update_data.assert_awaited_once_with(amount="12.50")
        self.assertIn("12.5 USD", message.answer.call_args.args[0])

    def test_decimal_expression_and_formatting_reject_ambiguous_values(self):
        self.assertEqual(balance.parse_balance_expression("12.50 + 0,25 USD", "USD"), Decimal("12.75"))
        self.assertEqual(balance.parse_balance_expression("25k + 1.50 ming"), Decimal("26500"))
        self.assertIsNone(balance.parse_balance_expression("10 USD", "UZS"))
        self.assertIsNone(balance.parse_balance_expression("1,000", "USD"))
        self.assertIsNone(balance.parse_balance_expression("-1", "USD"))
        self.assertEqual(commands.fmt(Decimal("9999999999999.99"), "USD"), "9 999 999 999 999.99 USD")

    def test_parser_uses_default_for_omitted_currency_and_logs_no_financial_content(self):
        parser = AIParser.__new__(AIParser)
        parser.model = "test-model"
        secret = "PRIVATE_INCOME_12225"
        response = {"transactions": [{"type": "expense", "amount": 12.35, "category": "Еда", "description": secret}]}
        create = MagicMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response)))]))
        parser.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with self.assertLogs("bot.services.ai_parser", level="DEBUG") as logs:
            parsed = parser._parse_sync(secret, "USD")
        self.assertEqual((parsed.transactions[0].currency, parsed.transactions[0].amount), ("USD", Decimal("12.35")))
        self.assertNotIn(secret, " ".join(logs.output))
        create.return_value.choices[0].message.content = json.dumps({"transactions": [{**response['transactions'][0], "amount": -1}]})
        with self.assertLogs("bot.services.ai_parser", level="ERROR") as logs, self.assertRaises(ValidationError):
            parser._parse_sync(secret, "USD")
        self.assertNotIn(secret, " ".join(logs.output))
        for invalid in ("-1", "0", "NaN", "Infinity", "1.001"):
            with self.subTest(amount=invalid), self.assertRaises(ValidationError):
                ParsedTransaction(type="expense", amount=invalid, category="Еда", description="test")
