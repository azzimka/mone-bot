"""Setup instructions and personal token management for Google Wallet auto-capture."""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.repositories import UserRepository
from bot.services.i18n import current_language

router = Router()


def _webhook_url() -> str:
    base = settings.effective_webhook_base_url
    if base:
        return f"{base}/webhook/google-pay"
    return "https://YOUR_DOMAIN/webhook/google-pay"


def _autopay_keyboard() -> InlineKeyboardMarkup:
    label = "🔄 Tokenni yangilash" if current_language.get() == "uz" else "🔄 Сбросить токен"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data="autopay:rotate"),
    ]])


def _autopay_message(token: str) -> str:
    url = escape(_webhook_url())
    safe_token = escape(token)
    body = escape('{"title":"[notif_title]","text":"[notif_text]"}')
    if current_language.get() == "uz":
        return (
            "💳 <b>Google Wallet (Android) avto-hisob</b>\n\n"
            "Google Wallet orqali to‘lov qilganingizda, bot xabarni avtomatik o‘qib, "
            "<b>✅ To‘g‘ri / ❌ Bekor qilish</b> tugmali kartochka yuboradi.\n\n"
            "<b>1. MacroDroid ilovasini o‘rnating</b> (Google Play, bepul) va bildirishnomalarga ruxsat bering.\n"
            "<b>2. Yangi makros yarating:</b>\n"
            "• <b>Trigger:</b> Bildirishnoma olindi (Notification Received) → ilova: <b>Google Wallet</b>\n"
            "• <b>Harakat (Action):</b> HTTP Request → <b>POST</b>\n"
            f"• <b>URL:</b>\n<code>{url}</code>\n"
            "• <b>Header (Заголовок):</b>\n"
            f"<code>Authorization: Bearer {safe_token}</code>\n"
            "• <b>Content-Type:</b> <code>application/json</code>\n"
            "• <b>Body (Matn):</b>\n"
            f"<code>{body}</code>\n\n"
            "🔒 <i>Tokenni hech kimga bermang. Kerak bo‘lsa pastdagi tugma bilan yangilang.</i>"
        )
    return (
        "💳 <b>Автораспознавание Google Wallet (Android)</b>\n\n"
        "После каждой оплаты через Google Wallet бот сам распознает покупку и пришлёт карточку с кнопками "
        "<b>✅ Верно / ❌ Отменить</b>.\n\n"
        "<b>1. Установите MacroDroid</b> (Google Play, бесплатно) и выдайте доступ к уведомлениям.\n"
        "<b>2. Создайте 1 макрос:</b>\n"
        "• <b>Триггер:</b> Уведомление получено (Notification Received) → приложение: <b>Google Wallet</b>\n"
        "• <b>Действие:</b> HTTP-запрос (HTTP Request) → метод <b>POST</b>\n"
        f"• <b>URL:</b>\n<code>{url}</code>\n"
        "• <b>Заголовок (Header):</b>\n"
        f"<code>Authorization: Bearer {safe_token}</code>\n"
        "• <b>Тип содержимого:</b> <code>application/json</code>\n"
        "• <b>Тело запроса (Body):</b>\n"
        f"<code>{body}</code>\n\n"
        "🔒 <i>Никому не передавайте этот токен. Если нужно — сбросьте его кнопкой ниже.</i>"
    )


@router.message(Command("autopay"))
async def cmd_autopay(message: Message, session: AsyncSession):
    if message.chat.type != "private":
        await message.answer(
            "Bu buyruq faqat shaxsiy chatda ishlaydi."
            if current_language.get() == "uz"
            else "Эта команда работает только в личном чате с ботом."
        )
        return
    _, token = await UserRepository.get_or_create_pay_token(
        session,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await session.commit()
    await message.answer(
        _autopay_message(token),
        parse_mode="HTML",
        reply_markup=_autopay_keyboard(),
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "autopay:rotate")
async def cb_rotate_autopay_token(callback: CallbackQuery, session: AsyncSession):
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer()
        return
    _, token = await UserRepository.rotate_pay_token(session, callback.from_user.id)
    await session.commit()
    await callback.message.edit_text(
        _autopay_message(token),
        parse_mode="HTML",
        reply_markup=_autopay_keyboard(),
        disable_web_page_preview=True,
    )
    await callback.answer(
        "Token yangilandi! MacroDroid’da yangisini kiriting."
        if current_language.get() == "uz"
        else "Токен обновлён! Замените его в MacroDroid.",
        show_alert=True,
    )
