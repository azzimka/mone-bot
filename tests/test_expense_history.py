"""Exercise the Telegram expense picker through its message and callback routes."""

import json
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

with patch.dict("os.environ", {
    "TELEGRAM_BOT_TOKEN": "123456789:bot-test-token",
    "GROQ_API_KEY": "test-key",
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
}):
    from bot.handlers import commands, expense_history
    from bot.main import DbSessionMiddleware, set_bot_commands

from bot.handlers.language import LanguageMiddleware
from bot.models import Base, Transaction, User

TODAY = date(2024, 2, 29)
SENDER = {"id": 111, "is_bot": False, "first_name": "Test"}


class ExpenseHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        pool = async_sessionmaker(self.engine, expire_on_commit=False)
        async with pool.begin() as session:
            user = User(telegram_id=111, language="ru")
            other = User(telegram_id=222, language="ru")
            session.add_all([user, other])
            await session.flush()
            session.add_all([
                Transaction(user_id=user.id, type="expense", amount=Decimal("25.25"), currency="UZS",
                            category="Еда", description="Кофе <&>", date=TODAY),
                Transaction(user_id=user.id, type="expense", amount=Decimal("3"), currency="USD",
                            category="Еда", date=TODAY),
                Transaction(user_id=user.id, type="expense", amount=Decimal("10"), currency="UZS",
                            category="Еда", date=date(2024, 2, 1)),
                Transaction(user_id=user.id, type="income", amount=Decimal("999"), currency="UZS", date=TODAY),
                Transaction(user_id=other.id, type="expense", amount=Decimal("888"), currency="UZS", date=TODAY),
                Transaction(user_id=user.id, type="expense", amount=Decimal("777"), currency="UZS",
                            date=date(2024, 3, 1)),
            ])
        self.pool = pool
        self.bot = Bot("123456789:bot-test-token")
        self.bot.session.make_request = AsyncMock(return_value=True)
        self.dp = Dispatcher()
        self.dp.update.middleware(DbSessionMiddleware(pool))
        language = LanguageMiddleware()
        self.dp.message.outer_middleware(language)
        self.dp.callback_query.outer_middleware(language)
        today = patch.object(expense_history, "local_today", return_value=TODAY)
        today.start()
        self.addCleanup(today.stop)
        self.addAsyncCleanup(self.bot.session.close)
        self.addAsyncCleanup(self.engine.dispose)
        self.dp.include_router(expense_history.router)
        self.addCleanup(setattr, expense_history.router, "_parent_router", None)

    async def feed(self, text=None, *, data=None, chat_id=111):
        message = {
            "message_id": 1, "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": chat_id, "type": "private"}, "from": SENDER,
        }
        if data is None:
            message["text"] = text
            payload = {"message": message}
        else:
            payload = {"callback_query": {
                "id": "callback-1", "chat_instance": "test", "message": message,
                "from": SENDER, "data": data,
            }}
        self.bot.session.make_request.reset_mock()
        await self.dp.feed_update(self.bot, Update.model_validate({"update_id": 1, **payload}))
        return [call.args[1] for call in self.bot.session.make_request.await_args_list]

    async def test_day_flow_highlights_today_and_excludes_other_dates_and_users(self):
        menu = (await self.feed("📅 История расходов"))[-1]
        day, _ = menu.reply_markup.inline_keyboard[0]
        months = (await self.feed(data=day.callback_data))[-1]
        self.assertEqual([button.text for row in months.reply_markup.inline_keyboard[:4] for button in row],
                         list(expense_history.MONTH_NAMES))
        february = months.reply_markup.inline_keyboard[0][1]
        days = (await self.feed(data=february.callback_data))[-1]
        dates = [button for row in days.reply_markup.inline_keyboard[:-1] for button in row]
        self.assertEqual(len(dates), 29)
        self.assertEqual(dates[-1].text, "🔹 29")
        self.assertTrue(all(button.model_extra == {} for button in dates[:-1]))
        wire_markup = json.loads(self.bot.session.prepare_value(days.reply_markup, self.bot, {}))
        self.assertEqual(wire_markup["inline_keyboard"][-2][-1]["style"], "primary")
        report = (await self.feed(data=dates[-1].callback_data))[-1]
        self.assertIn("29.02.2024", report.text)
        self.assertIn("Кофе &lt;&amp;&gt;", report.text)
        self.assertIn("Итого: 3 USD · 25.25 UZS", report.text)
        for unrelated in ("999", "888", "777", "10 UZS"):
            self.assertNotIn(unrelated, report.text)

    async def test_month_flow_and_old_month_buttons(self):
        menu = (await self.feed("📅 История расходов"))[-1]
        month = menu.reply_markup.inline_keyboard[0][1]
        months = (await self.feed(data=month.callback_data))[-1]
        february = months.reply_markup.inline_keyboard[0][1]
        for data in (february.callback_data, "month_report:2024-02"):
            report = (await self.feed(data=data))[-1]
            self.assertIn("Февраль 2024", report.text)
            self.assertIn("Итого: 3 USD · 35.25 UZS", report.text)
            self.assertNotIn("Кофе", report.text)
        previous_year = months.reply_markup.inline_keyboard[-2][0]
        months = (await self.feed(data=previous_year.callback_data))[-1]
        february = months.reply_markup.inline_keyboard[0][1]
        self.assertIn("Расходов нет.", (await self.feed(data=february.callback_data))[-1].text)

    async def test_picker_uses_saved_uzbek_language(self):
        async with self.pool.begin() as session:
            user = await session.get(User, 1)
            user.language = "uz"
        menu = (await self.feed("📅 Chiqimlar tarixi"))[-1]
        day, month = menu.reply_markup.inline_keyboard[0]
        self.assertEqual((day.text, month.text), ("☀️ Kunlik", "🗓️ Oylik"))
        months = (await self.feed(data=month.callback_data))[-1]
        self.assertEqual(months.reply_markup.inline_keyboard[0][0].text, "Yanvar")
        self.assertEqual(months.reply_markup.inline_keyboard[3][-1].text, "Dekabr")

    async def test_invalid_date_and_cross_chat_callback_are_acknowledged(self):
        await self.feed("📅 История расходов")
        invalid = expense_history.HistoryAction(view="day", year=2023, month=2, day=29)
        response = await self.feed(data=invalid.pack())
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0].text, "Некорректная дата.")
        action = expense_history.HistoryAction(view="month", year=2024, month=2)
        response = await self.feed(data=action.pack(), chat_id=222)
        self.assertEqual(len(response), 1)
        self.assertIsNone(response[0].text)

    async def test_long_report_can_be_paged_without_losing_the_total(self):
        async with self.pool.begin() as session:
            session.add_all([
                Transaction(user_id=1, type="expense", amount=Decimal("1"), currency="UZS",
                            description=f"Покупка {index}", date=TODAY)
                for index in range(15)
            ])
        first = (await self.feed("/today"))[-1]
        self.assertIn("Страница 1 из 2", first.text)
        next_page = first.reply_markup.inline_keyboard[0][0]
        second = (await self.feed(data=next_page.callback_data))[-1]
        self.assertIn("Страница 2 из 2", second.text)
        self.assertIn("Покупка 14", second.text)
        for page in (first, second):
            self.assertIn("Итого: 3 USD · 40.25 UZS", page.text)

    async def test_reply_keyboard_keeps_history_and_slash_menu_only_shows_start(self):
        keyboard = commands.get_main_keyboard()
        self.assertEqual([button.text for row in keyboard.keyboard for button in row],
                         ["💰 Баланс", "📋 Расходы за сегодня", "📅 История расходов"])
        await set_bot_commands(self.bot)
        await commands.configure_chat_menu(self.bot, 111)
        requests = [call.args[1] for call in self.bot.session.make_request.await_args_list]
        for request in requests[:2]:
            self.assertEqual([command.command for command in request.commands], ["start"])
        self.assertEqual(requests[1].scope.chat_id, 111)
        self.assertEqual(requests[-1].menu_button.type, "default")
