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


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🇺🇿 O‘zbekcha", callback_data="language:uz"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="language:ru"),
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
            custom = (await session.execute(select(Category).where(Category.user_id==user.id))).scalars().all()
            current_category_names.set({item.name:(item.name_ru if user.language=='ru' else item.name_uz) or item.display_name for item in custom if (item.name_ru if user.language=='ru' else item.name_uz) or item.display_name})
            data["mone_user"] = user
            is_choice = isinstance(event, CallbackQuery) and bool(re.fullmatch(r"language:(uz|ru)", event.data or ""))
            if user.language is None and not is_choice:
                message = event if isinstance(event, Message) else event.message
                if isinstance(event, CallbackQuery):
                    await event.answer()
                if message is None:
                    return
                if message.chat.type != "private":
                    await message.answer("Tilni botning shaxsiy chatida tanlang. / Выберите язык в личном чате с ботом.")
                    return
                await session.commit()
                await message.answer(CHOICE, reply_markup=language_keyboard())
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
    await UserRepository.get_or_create(session, message.from_user.id)
    await state.clear()
    await message.answer(CHOICE, reply_markup=language_keyboard())


@router.callback_query(F.data.regexp(r"^language:(uz|ru)$"))
async def save_language(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    message = callback.message
    if message is None or message.chat.type != "private" or message.chat.id != callback.from_user.id:
        await callback.answer()
        return
    _, language = callback.data.split(":", 1)
    user = await UserRepository.set_language(session, callback.from_user.id, language)
    await session.commit()
    await state.clear()
    token = current_language.set(language)
    try:
        await callback.answer(tr("Til saqlandi."))
        await message.edit_text(tr("Til saqlandi."))
        from bot.handlers.commands import send_welcome
        await send_welcome(message, user.first_name, callback.bot, user.telegram_id)
    finally:
        current_language.reset(token)
