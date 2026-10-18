"""Choose language in private chat; persist it against the verified Telegram user."""

import logging
import re

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from bot.models import Category
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.repositories import UserRepository
from bot.services.i18n import current_category_names, current_language, tr

router = Router()
logger = logging.getLogger(__name__)
CHOICE = "Tilni tanlang / Выберите язык:"


def language_keyboard(request_id: str = "") -> InlineKeyboardMarkup:
    suffix = f":{request_id}" if request_id else ""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇺🇿 O‘zbekcha", callback_data=f"language:uz{suffix}"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data=f"language:ru{suffix}"),
    ]])


class LanguageMiddleware(BaseMiddleware):
    def __init__(self):
        self._menu_languages: dict[int, str] = {}

    async def __call__(self, handler, event: Message | CallbackQuery, data):
        session = data["session"]
        sender = event.from_user
        if sender is None:
            return await handler(event, data)
        user = await UserRepository.get_or_create(session, sender.id, sender.username, sender.first_name)
        token = current_language.set(user.language or "uz")
        category_token = current_category_names.set(None)
        try:
            custom = (await session.execute(select(Category.name, Category.display_name).where(
                Category.user_id == user.id, Category.display_name.is_not(None)))).all()
            current_category_names.set(dict(custom))
            data["mone_user"] = user
            is_choice = isinstance(event, CallbackQuery) and bool(re.fullmatch(r"language:(uz|ru)(?::[a-f0-9]{32})?", event.data or ""))
            if user.language is None and not is_choice:
                message = event if isinstance(event, Message) else event.message
                if isinstance(event, CallbackQuery):
                    await event.answer()
                if message is None:
                    return
                if message.chat.type != "private":
                    await message.answer("Tilni botning shaxsiy chatida tanlang. / Выберите язык в личном чате с ботом.")
                    return
                match = re.fullmatch(r"/start(?:@\w+)? web_([a-f0-9]{32})", message.text or "")
                await session.commit()
                await message.answer(CHOICE, reply_markup=language_keyboard(match.group(1) if match else ""))
                return
            if user.language and data.get("bot") and self._menu_languages.get(user.telegram_id) != user.language:
                from bot.handlers.commands import configure_chat_menu
                if await configure_chat_menu(data["bot"], user.telegram_id):
                    self._menu_languages[user.telegram_id] = user.language
            return await handler(event, data)
        finally:
            current_category_names.reset(category_token)
            current_language.reset(token)


@router.message(Command("language"))
@router.message(F.text.regexp(r"^/start(?:@\w+)? language$"))
async def choose_language(message: Message, state: FSMContext, session: AsyncSession):
    if message.chat.type != "private":
        await message.answer("Tilni botning shaxsiy chatida tanlang. / Выберите язык в личном чате с ботом.")
        return
    user = await UserRepository.get_or_create(session, message.from_user.id)
    await state.clear()
    if user.language is not None:
        from bot.handlers.commands import send_settings_link
        await send_settings_link(message)
        return
    await message.answer(CHOICE, reply_markup=language_keyboard())


@router.callback_query(F.data.regexp(r"^language:(uz|ru)(?::[a-f0-9]{32})?$"))
async def save_language(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    message = callback.message
    if message is None or message.chat.type != "private" or message.chat.id != callback.from_user.id:
        await callback.answer()
        return
    _, language, *continuation = callback.data.split(":")
    existing = await UserRepository.get_or_create(session, callback.from_user.id)
    if existing.language is not None:
        await callback.answer()
        if continuation:
            from bot.handlers.web_login import show_web_login
            await show_web_login(message, continuation[0], session)
        else:
            from bot.handlers.commands import send_settings_link
            await send_settings_link(message)
        return
    user = await UserRepository.set_language(session, callback.from_user.id, language)
    await session.commit()
    await state.clear()
    token = current_language.set(language)
    try:
        await callback.answer(tr("Til saqlandi."))
        await message.edit_text(tr("Til saqlandi. Bot va website hisobingizda shu til ishlatiladi. Tilni website sozlamasida o‘zgartirasiz."))
        from bot.handlers.commands import send_welcome
        await send_welcome(message, user.first_name, callback.bot, user.telegram_id)
        if continuation:
            from bot.handlers.web_login import show_web_login
            await show_web_login(message, continuation[0], session)
    finally:
        current_language.reset(token)
