from bot.services.i18n import tr, button_variants
"""Private-chat CSV upload, preview and owner-scoped confirmation."""

import asyncio
import io
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.csv_imports import finish_import, stage_import
from bot.database.repositories import UserRepository
from bot.services.csv_import import CsvImportError, MAX_FILE_BYTES, format_preview, parse_csv

logger = logging.getLogger(__name__)
router = Router()

@router.message(Command("import"))
async def cmd_import(message: Message):
    await message.answer(tr("csv_import_help"))


@router.message(F.document)
async def upload_csv(message: Message, bot: Bot, session: AsyncSession):
    if message.chat.type != "private":
        await message.answer(tr("Moliyaviy CSV faylni botga shaxsiy chatda yuboring."))
        return
    document = message.document
    if not document.file_name or not document.file_name.lower().endswith(".csv"):
        await message.answer(tr('Отправьте файл с расширением .csv. Пример и инструкция: /import'))
        return
    if document.file_size is None or document.file_size > MAX_FILE_BYTES:
        await message.answer("CSV hajmi 1 МБ dan oshmasligi kerak.")
        return
    try:
        buffer = io.BytesIO()
        await bot.download(document, destination=buffer)
        data = buffer.getvalue()
        user = await UserRepository.get_or_create(
            session, message.from_user.id, message.from_user.username, message.from_user.first_name)
        preview = await asyncio.to_thread(parse_csv, data, user.default_currency)
        item = await stage_import(session, user.id, document.file_name, data, preview)
        import_id = item.id
        # Persist the original CSV and preview before exposing confirmation buttons.
        await session.commit()
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=tr('Tasdiqlash / Импортировать'), callback_data=f"csv:confirm:{import_id}"),
            InlineKeyboardButton(text=tr('Bekor qilish / Отмена'), callback_data=f"csv:cancel:{import_id}"),
        ]])
        await message.answer(format_preview(preview), reply_markup=keyboard)
    except CsvImportError as exc:
        await session.rollback()
        await message.answer(str(exc))
    except Exception as exc:
        await session.rollback()
        logger.error("CSV upload failed (%s)", type(exc).__name__)
        await message.answer(tr("CSVni tayyorlashda xatolik. Qayta yuboring yoki /import ko‘rsatmasini tekshiring."))


@router.callback_query(F.data.startswith("csv:confirm:") | F.data.startswith("csv:cancel:"))
async def confirm_csv(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if not callback.message or callback.message.chat.type != "private":
        return
    _, action, import_id = callback.data.split(":", 2)
    try:
        count = await finish_import(session, import_id, callback.from_user.id, cancel=action == "cancel")
        # A failure cannot acknowledge a successful ledger write or consume the pending import.
        await session.commit()
    except CsvImportError as exc:
        await session.rollback()
        # Do not alter another user's preview or a previously completed success message.
        await callback.message.answer(str(exc))
        return
    except Exception as exc:
        await session.rollback()
        logger.error("CSV import failed (%s)", type(exc).__name__)
        await callback.message.answer(tr("Import saqlanmadi. Tasdiqlash tugmasini qayta bosing."))
        return
    result = (tr('CSV import qilindi: {p1} ta operatsiya saqlandi.\nИмпорт завершён. Отчёты: /today, /week, /month.' ,p1=f'{count}')) if action == "confirm" else tr("CSV import bekor qilindi.")
    await callback.message.edit_text(result)
