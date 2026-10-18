import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import CallbackQuery, Message
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.database.repositories import UserRepository
from bot.database.schema import initialize_schema
from bot.handlers.language import LanguageMiddleware, language_keyboard, save_language
from bot.models import Category, User, WebLoginRequest
from bot.services.i18n import UZBEK, RUSSIAN, current_language, current_category_names, category_label, tr, button_variants
from bot.services.web_auth import request_login


class LanguageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await initialize_schema(self.engine)
        self.pool = async_sessionmaker(self.engine, expire_on_commit=False)
        self.session = self.pool()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    def message(self, text="/start", user_id=111):
        message = MagicMock(spec=Message)
        message.from_user = SimpleNamespace(id=user_id, username="mirzo", first_name="Mirzo")
        message.chat = SimpleNamespace(id=user_id, type="private")
        message.text = text
        message.answer = AsyncMock()
        message.edit_text = AsyncMock()
        return message

    def callback(self, language="ru", request_id=""):
        callback = MagicMock(spec=CallbackQuery)
        callback.message = self.message()
        callback.from_user = callback.message.from_user
        callback.data = f"language:{language}" + (f":{request_id}" if request_id else "")
        callback.answer = AsyncMock()
        callback.bot = MagicMock()
        return callback

    async def test_custom_category_names_follow_account_and_reset_after_handler(self):
        user = await UserRepository.set_language(self.session, 111, "ru")
        other = await UserRepository.set_language(self.session, 222, "ru")
        self.session.add(Category(user_id=user.id, name="Еда", display_name="Meals", icon="food"))
        self.session.add(Category(user_id=other.id, name="Еда", display_name="Other meals", icon="food"))
        await self.session.flush()
        before = current_category_names.get()
        async def handler(event, data):
            self.assertEqual(category_label("Еда"), "Meals")
        await LanguageMiddleware()(handler, self.message(), {"session": self.session})
        self.assertIs(current_category_names.get(), before)
        with self.assertRaises(RuntimeError):
            await LanguageMiddleware()(AsyncMock(side_effect=RuntimeError("failure")), self.message(), {"session": self.session})
        self.assertIs(current_category_names.get(), before)

    async def test_legacy_category_schema_is_upgraded_without_losing_names_or_icons(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE categories (id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, icon VARCHAR(10), user_id INTEGER, is_default BOOLEAN NOT NULL)"))
            await conn.execute(text("INSERT INTO categories VALUES (1, 'Еда', '🍔', NULL, 1)"))
        await initialize_schema(engine)
        await initialize_schema(engine)
        pool = async_sessionmaker(engine)
        async with pool() as session:
            item = await session.get(Category, 1)
            self.assertEqual((item.name, item.icon), ("Еда", "🍔"))
            self.assertIsNone(item.display_name)
            self.assertIsNone(item.parent_name)
        await engine.dispose()

    async def test_first_message_requires_explicit_selection(self):
        message = self.message("Qahva 25000")
        handler = AsyncMock()
        await LanguageMiddleware()(handler, message, {"session": self.session})
        handler.assert_not_awaited()
        message.answer.assert_awaited_once()
        keyboard = message.answer.call_args.kwargs["reply_markup"]
        self.assertEqual([b.callback_data for b in keyboard.inline_keyboard[0]], ["language:uz", "language:ru"])
        user = (await self.session.execute(select(User))).scalar_one()
        self.assertIsNone(user.language)

    async def test_selection_is_durable_and_does_not_change_another_user(self):
        await UserRepository.set_language(self.session, 222, "uz")
        callback = self.callback("ru")
        welcome = AsyncMock()
        with patch.dict("sys.modules", {"bot.handlers.commands": SimpleNamespace(send_welcome=welcome)}):
            await save_language(callback, self.session, SimpleNamespace(clear=AsyncMock()))
        callback.message.edit_text.assert_awaited_once()
        self.assertIn("Язык сохранён", callback.message.edit_text.call_args.args[0])
        async with self.pool() as other_browser:
            user = await UserRepository.get_or_create(other_browser, 111, "new_name", "Changed")
            self.assertEqual(user.language, "ru")
            other = await UserRepository.get_or_create(other_browser, 222)
            self.assertEqual(other.language, "uz")
        handler = AsyncMock(return_value="handled")
        original = current_language.get()
        async def check_locale(event, data):
            self.assertEqual(current_language.get(), "ru")
            return "handled"
        handler.side_effect = check_locale
        self.assertEqual(await LanguageMiddleware()(handler, self.message(), {"session": self.session}), "handled")
        self.assertEqual(current_language.get(), original)

    async def test_preference_context_resets_on_handler_failure(self):
        await UserRepository.set_language(self.session, 111, "uz")
        original = current_language.get()
        with self.assertRaises(RuntimeError):
            await LanguageMiddleware()(AsyncMock(side_effect=RuntimeError("failed")), self.message(), {"session": self.session})
        self.assertEqual(current_language.get(), original)

    async def test_web_login_continues_after_selection_but_still_needs_approval(self):
        item, _ = await request_login(self.session)
        await self.session.commit()
        message = self.message(f"/start web_{item.id}")
        await LanguageMiddleware()(AsyncMock(), message, {"session": self.session})
        buttons = message.answer.call_args.kwargs["reply_markup"].inline_keyboard[0]
        self.assertTrue(all(button.callback_data.endswith(item.id) for button in buttons))
        callback = self.callback("uz", item.id)
        with patch.dict("sys.modules", {"bot.handlers.commands": SimpleNamespace(send_welcome=AsyncMock())}):
            await save_language(callback, self.session, SimpleNamespace(clear=AsyncMock()))
        self.assertIn(item.id[:6].upper(), callback.message.answer.call_args.args[0])
        self.assertEqual(callback.message.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data, f"web_login:{item.id}")
        self.assertIsNone((await self.session.get(WebLoginRequest, item.id)).user_id)

    async def test_selection_cannot_change_a_different_chat_or_accept_unknown_language(self):
        callback = self.callback()
        callback.message.chat.id = 222
        await save_language(callback, self.session, SimpleNamespace(clear=AsyncMock()))
        self.assertIsNone((await self.session.execute(select(User))).scalar_one_or_none())
        with self.assertRaises(ValueError):
            await UserRepository.set_language(self.session, 111, "en")

    async def test_old_bot_language_buttons_cannot_override_website_preference(self):
        await UserRepository.set_language(self.session, 111, "ru")
        await self.session.commit()
        link = AsyncMock()
        with patch.dict("sys.modules", {"bot.handlers.commands": SimpleNamespace(send_settings_link=link)}):
            await save_language(self.callback("uz"), self.session, SimpleNamespace(clear=AsyncMock()))
        self.assertEqual((await UserRepository.get_or_create(self.session, 111)).language, "ru")
        link.assert_awaited_once()

    async def test_bot_menu_resyncs_when_saved_account_language_changes(self):
        await UserRepository.set_language(self.session, 111, "uz")
        configure = AsyncMock(return_value=True)
        middleware = LanguageMiddleware()
        data = {"session": self.session, "bot": object()}
        with patch.dict("sys.modules", {"bot.handlers.commands": SimpleNamespace(configure_chat_menu=configure)}):
            await middleware(AsyncMock(), self.message(), data)
            await middleware(AsyncMock(), self.message(), data)
            self.assertEqual(configure.await_count, 1)
            await UserRepository.set_language(self.session, 111, "ru")
            await middleware(AsyncMock(), self.message(), data)
            self.assertEqual(configure.await_count, 2)

    async def test_existing_database_is_upgraded_without_changing_user_data(self):
        legacy = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with legacy.begin() as conn:
                await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id BIGINT UNIQUE NOT NULL, username VARCHAR(255), first_name VARCHAR(255), default_currency VARCHAR(10) NOT NULL, created_at DATETIME, updated_at DATETIME)"))
                await conn.execute(text("INSERT INTO users (id, telegram_id, first_name, default_currency) VALUES (1, 99, 'Legacy', 'UZS')"))
            await initialize_schema(legacy)
            await initialize_schema(legacy)
            async with legacy.connect() as conn:
                row = (await conn.execute(text("SELECT telegram_id, first_name, default_currency, language FROM users"))).one()
                self.assertEqual(tuple(row), (99, "Legacy", "UZS", None))
        finally:
            await legacy.dispose()

    def test_translations_preserve_parameters_and_keyboard_compatibility(self):
        from string import Formatter
        fields = lambda phrase: sorted(name for _, name, _, _ in Formatter().parse(phrase) if name is not None)
        for dictionary in (UZBEK, RUSSIAN):
            for key, translation in dictionary.items():
                self.assertEqual(fields(key), fields(translation), key)
        self.assertEqual(button_variants("💰 Баланс"), {"💰 Баланс", "💰 Balans"})
