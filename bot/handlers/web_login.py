import re

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.repositories import UserRepository
from bot.models.web_session import WebLoginRequest
from bot.services.web_auth import approve_login, is_expired

router = Router()


@router.message(CommandStart(deep_link=True), F.text.regexp(r"^/start(?:@\w+)? web_[a-f0-9]{32}$"))
async def start_web_login(message: Message, command: CommandObject, session: AsyncSession):
    if message.chat.type != "private":
        return
    request_id = command.args.removeprefix("web_")
    item = await session.get(WebLoginRequest, request_id)
    if item is None or item.consumed or item.user_id is not None or is_expired(item.expires_at):
        await message.answer("Kirish havolasi eskirgan. Website’da yangi so‘rov yarating.")
        return
    await message.answer(
        f"Mone web kabinetiga kirish\n\nTekshirish kodi: {request_id[:6].upper()}\n\n"
        "Website’da ham aynan shu kod ko‘rsatilganini tekshiring. "
        "Faqat kirishni o‘zingiz boshlagan bo‘lsangiz tasdiqlang. "
        "Tasdiqlash shu brauzerga moliyaviy ma’lumotlaringizni ochadi.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Kirishni tasdiqlash", callback_data=f"web_login:{request_id}")
        ]]),
    )


@router.callback_query(F.data.startswith("web_login:"))
async def confirm_web_login(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    if not callback.message or callback.message.chat.type != "private":
        return
    request_id = callback.data.split(":", 1)[1]
    if not re.fullmatch(r"[a-f0-9]{32}", request_id):
        return
    user = await UserRepository.get_or_create(session, callback.from_user.id,
                                             callback.from_user.username, callback.from_user.first_name)
    approved = await approve_login(session, request_id, user.id)
    await session.commit()
    await callback.message.edit_text("Kirish tasdiqlandi. Website’ga qayting." if approved
                                    else "Bu so‘rov eskirgan yoki avval tasdiqlangan.")
