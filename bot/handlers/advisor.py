"""Telegram bot handler for the read-only AI financial advisor mode."""

from __future__ import annotations

from contextlib import suppress
import html
import logging
import os
import tempfile
import time
from typing import Any
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    ContentType,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.repositories import UserRepository
from bot.services.ai_advisor import (
    AIAdvisor,
    compute_live_accounts,
    format_telegram_html,
    split_telegram_message,
)
from bot.services.i18n import button_variants, current_language, tr
from bot.services.speech import SpeechService
from bot.services.tts import ElevenLabsTTSService, TTSError, strip_tts_tags

logger = logging.getLogger(__name__)
router = Router()

PENDING_QUESTION_TTL_SECONDS = 1800
MAX_PENDING_QUESTIONS = 5000

ai_advisor = AIAdvisor(
    api_key=settings.GROQ_API_KEY,
    max_concurrency=settings.ADVISOR_LLM_CONCURRENCY,
)
speech_service = SpeechService(api_key=settings.GROQ_API_KEY)
tts_service = ElevenLabsTTSService(
    api_key=settings.ELEVENLABS_API_KEY,
    voice_id=settings.ELEVENLABS_VOICE_ID,
    model_id=settings.ELEVENLABS_MODEL_ID,
    output_format=settings.ELEVENLABS_OUTPUT_FORMAT,
    stability=settings.ELEVENLABS_STABILITY,
    similarity_boost=settings.ELEVENLABS_SIMILARITY_BOOST,
    max_chars=settings.ELEVENLABS_MAX_CHARS,
    max_concurrency=settings.ELEVENLABS_MAX_CONCURRENCY,
)

pending_advisor_questions: dict[str, dict[str, Any]] = {}
processing_advisor_questions: set[str] = set()
active_advisor_users: set[int] = set()


class AdvisorStates(StatesGroup):
    """FSM state for interactive read-only consultation with the AI financier."""

    chatting = State()


async def close_services() -> None:
    """Close shared network clients cleanly on bot shutdown."""
    await tts_service.close()
    await ai_advisor.close()
    await speech_service.close()


def _prune_pending_questions(now: float | None = None) -> None:
    ts = now if now is not None else time.monotonic()
    expired = [
        qid
        for qid, payload in pending_advisor_questions.items()
        if ts - float(payload.get("created_at", ts)) > PENDING_QUESTION_TTL_SECONDS
    ]
    for qid in expired:
        pending_advisor_questions.pop(qid, None)
    while len(pending_advisor_questions) > MAX_PENDING_QUESTIONS:
        oldest_key = next(iter(pending_advisor_questions))
        pending_advisor_questions.pop(oldest_key, None)


def get_advisor_keyboard() -> ReplyKeyboardMarkup:
    """Reply keyboard dedicated to AI financier consultation mode."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=tr("📊 Разбор за месяц")),
                KeyboardButton(text=tr("🔍 На что я часто трачу?")),
            ],
            [
                KeyboardButton(text=tr("💡 Проверить покупку")),
                KeyboardButton(text=tr("🗑 Новый диалог")),
            ],
            [
                KeyboardButton(text=tr("⬅️ Выйти из режима")),
            ],
        ],
        resize_keyboard=True,
        persistent=True,
    )


def get_format_choice_keyboard(question_id: str) -> InlineKeyboardMarkup:
    """Step 1 inline buttons: voice vs text."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr("🎙 Голосом"),
                    callback_data=f"adv_fmt:{question_id}:voice",
                ),
                InlineKeyboardButton(
                    text=tr("📝 Текстом"),
                    callback_data=f"adv_fmt:{question_id}:text",
                ),
            ]
        ]
    )


def get_detail_choice_keyboard(question_id: str, fmt: str) -> InlineKeyboardMarkup:
    """Step 2 inline buttons: brief (~500-600 chars) vs detailed (~1000-1100 chars)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=tr("⚡ По делу"),
                    callback_data=f"adv_len:{question_id}:{fmt}:brief",
                ),
                InlineKeyboardButton(
                    text=tr("📖 Подробно"),
                    callback_data=f"adv_len:{question_id}:{fmt}:detailed",
                ),
            ]
        ]
    )


async def _send_advisor_reply(
    message: Message,
    raw_text: str,
    reply_markup: ReplyKeyboardMarkup | None = None,
) -> None:
    kb = reply_markup or get_advisor_keyboard()
    formatted = format_telegram_html(raw_text)
    for chunk in split_telegram_message(formatted, limit=3900):
        await message.answer(
            chunk,
            parse_mode="HTML",
            reply_markup=kb,
        )


async def _prompt_response_format(message: Message, question: str) -> None:
    """Store question and ask how the user wants the reply before running LLM/TTS."""
    cleaned = (question or "").strip()
    if not cleaned:
        return

    _prune_pending_questions()
    qid = uuid.uuid4().hex[:12]
    pending_advisor_questions[qid] = {
        "user_telegram_id": message.from_user.id,
        "question": cleaned,
        "created_at": time.monotonic(),
    }
    await message.answer(
        tr("Как тебе удобнее получить ответ?"),
        reply_markup=get_format_choice_keyboard(qid),
    )


async def _reply_markup_for_state(state: FSMContext) -> ReplyKeyboardMarkup:
    if await state.get_state() == AdvisorStates.chatting.state:
        return get_advisor_keyboard()
    from bot.handlers.commands import get_main_keyboard

    return get_main_keyboard()


async def _get_owned_pending(callback: CallbackQuery, qid: str) -> dict[str, Any] | None:
    pending = pending_advisor_questions.get(qid)
    if pending is None:
        await callback.answer(
            tr("⚠️ Этот запрос уже обработан или устарел. Отправь вопрос заново."),
            show_alert=True,
        )
        if callback.message:
            with suppress(Exception):
                await callback.message.edit_reply_markup(reply_markup=None)
        return None

    user_tg_id = callback.from_user.id
    if pending["user_telegram_id"] != user_tg_id:
        await callback.answer(
            tr("Этот вопрос принадлежит другому пользователю."),
            show_alert=True,
        )
        return None

    if qid in processing_advisor_questions:
        await callback.answer(tr("⏳ Этот вопрос уже обрабатывается…"))
        return None

    return pending


@router.callback_query(F.data.startswith("adv_fmt:"))
async def on_advisor_format_selected(callback: CallbackQuery) -> None:
    """Step 1: store voice/text format and ask detail level (zero LLM/TTS calls yet)."""
    parts = (callback.data or "").split(":", 2)
    if len(parts) != 3 or parts[2] not in {"voice", "text"}:
        await callback.answer()
        return

    _, qid, fmt = parts
    pending = await _get_owned_pending(callback, qid)
    if pending is None:
        return

    pending["format"] = fmt
    pending["created_at"] = time.monotonic()
    await callback.answer()
    if callback.message:
        await callback.message.edit_text(
            tr("Как вам ответить?"),
            reply_markup=get_detail_choice_keyboard(qid, fmt),
        )


@router.callback_query(F.data.startswith("adv_len:"))
async def on_advisor_detail_selected(
    callback: CallbackQuery,
    bot: Bot,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Step 2: generate advisor reply with chosen format and detail level."""
    parts = (callback.data or "").split(":", 3)
    if len(parts) != 4 or parts[2] not in {"voice", "text"} or parts[3] not in {"brief", "detailed"}:
        await callback.answer()
        return

    _, qid, fmt, detail = parts
    pending = await _get_owned_pending(callback, qid)
    if pending is None:
        return

    user_tg_id = callback.from_user.id
    if user_tg_id in active_advisor_users:
        await callback.answer(tr("⏳ Готовлю ответ, подожди пару секунд…"))
        return

    # Claim atomically before any await to guarantee at-most-once execution
    pending_advisor_questions.pop(qid, None)
    processing_advisor_questions.add(qid)
    active_advisor_users.add(user_tg_id)

    try:
        await callback.answer()
        status_text = (
            tr("⏳ Анализирую финансы и записываю голосовой ответ…")
            if fmt == "voice"
            else tr("⏳ Анализирую финансы…")
        )
        if callback.message:
            with suppress(Exception):
                await callback.message.edit_text(status_text, reply_markup=None)

        chat_id = callback.message.chat.id if callback.message else user_tg_id
        with suppress(Exception):
            await bot.send_chat_action(
                chat_id=chat_id,
                action="record_voice" if fmt == "voice" else "typing",
            )

        user = await UserRepository.get_or_create(
            session,
            user_tg_id,
            callback.from_user.username,
            callback.from_user.first_name,
        )
        reply_kb = await _reply_markup_for_state(state)

        answer = await ai_advisor.ask(
            session,
            user,
            pending["question"],
            response_mode=fmt,
            detail_level=detail,
        )

        target_msg = callback.message
        if target_msg is None:
            return

        if fmt == "voice":
            tts_limit = 750 if detail == "brief" else settings.ELEVENLABS_MAX_CHARS
            try:
                with suppress(Exception):
                    await bot.send_chat_action(chat_id=chat_id, action="record_voice")
                audio_bytes = await tts_service.synthesize(answer, max_chars=tts_limit)
                with suppress(Exception):
                    await target_msg.delete()
                await target_msg.answer_voice(
                    voice=BufferedInputFile(audio_bytes, filename="advisor_reply.ogg"),
                    reply_markup=reply_kb,
                )
                return
            except TTSError as exc:
                logger.warning("Advisor TTS fallback to text (%s): %s", type(exc).__name__, exc)
                with suppress(Exception):
                    await target_msg.delete()
                await target_msg.answer(
                    tr("⚠️ Голосовая озвучка сейчас недоступна (проверьте ключ ElevenLabs), отвечаю текстом:"),
                    reply_markup=reply_kb,
                )
                await _send_advisor_reply(
                    target_msg,
                    strip_tts_tags(answer) or answer,
                    reply_markup=reply_kb,
                )
                return

        with suppress(Exception):
            await target_msg.delete()
        await _send_advisor_reply(target_msg, answer, reply_markup=reply_kb)
    except Exception as exc:
        logger.error("AI advisor failed (%s)", type(exc).__name__, exc_info=True)
        if callback.message:
            reply_kb = await _reply_markup_for_state(state)
            with suppress(Exception):
                await callback.message.edit_text(
                    tr("⚠️ Не удалось получить ответ AI-финансиста. Попробуй ещё раз через пару секунд."),
                    reply_markup=None,
                )
            with suppress(Exception):
                await callback.message.answer(
                    tr("⚠️ Не удалось получить ответ AI-финансиста. Попробуй ещё раз через пару секунд."),
                    reply_markup=reply_kb,
                )
    finally:
        processing_advisor_questions.discard(qid)
        active_advisor_users.discard(user_tg_id)


@router.message(StateFilter("*"), F.text.in_(button_variants("🧠 AI-финансист")))
@router.message(StateFilter("*"), Command("advisor"))
async def enter_advisor_mode(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    """Activate read-only AI financier mode without disturbing ledger state."""
    user = await UserRepository.get_or_create(
        session,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await state.set_state(AdvisorStates.chatting)

    accounts = await compute_live_accounts(session, user)
    active = [a for a in accounts if not a["archived"]]
    if active:
        balances_preview = ", ".join(
            f"{html.escape(a['name'])}: <b>{html.escape(a['balance'])} {html.escape(a['currency'])}</b>"
            for a in active[:4]
        )
    else:
        balances_preview = html.escape(tr("счета пока не заведены"))

    if current_language.get() == "uz":
        intro = (
            "🧠 <b>AI-moliyachi rejimi yoqildi</b>\n\n"
            f"💳 Hozirgi hisoblar: {balances_preview}\n\n"
            "Savolingizni matn yoki ovozli xabar orqali yuboring — yoki pastdagi tayyor tugmalardan foydalaning."
        )
    else:
        intro = (
            "🧠 <b>Режим AI-финансиста включён</b>\n\n"
            f"💳 Сейчас на счетах: {balances_preview}\n\n"
            "Пиши или надиктуй голосом любой финансовый вопрос — или нажми быструю кнопку ниже."
        )

    await message.answer(
        intro,
        parse_mode="HTML",
        reply_markup=get_advisor_keyboard(),
    )


@router.message(StateFilter(AdvisorStates.chatting), F.text.in_(button_variants("⬅️ Выйти из режима")))
@router.message(StateFilter(AdvisorStates.chatting), Command("exit"))
async def exit_advisor_mode(message: Message, state: FSMContext) -> None:
    """Exit AI financier mode and restore the standard transaction entry keyboard."""
    from bot.handlers.commands import get_main_keyboard

    await state.clear()
    await message.answer(
        tr("✅ Вышел из режима AI-финансиста. Обычные сообщения снова записывают доходы и расходы."),
        reply_markup=get_main_keyboard(),
    )


@router.message(StateFilter(AdvisorStates.chatting), F.text.in_(button_variants("🗑 Новый диалог")))
async def clear_advisor_dialog(
    message: Message,
    session: AsyncSession,
) -> None:
    """Clear stored conversation turns while keeping all ledger data intact."""
    user = await UserRepository.get_or_create(
        session,
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    await ai_advisor.clear_history(session, user.id)
    await message.answer(
        tr("🧹 История диалога очищена. База операций на месте — задавай новый вопрос."),
        reply_markup=get_advisor_keyboard(),
    )


@router.message(StateFilter(AdvisorStates.chatting), F.text.in_(button_variants("📊 Разбор за месяц")))
async def quick_month_review(message: Message) -> None:
    prompt = (
        "Joriy oy bo‘yicha to‘liq moliyaviy tahlil qilib ber: hisob qoldiqlari, kirim va chiqim, "
        "jamg‘arma ulushi, byudjet sur’ati, o‘tgan oy bilan taqqoslash hamda asosiy xavflar va tavsiyalar."
        if current_language.get() == "uz"
        else "Сделай полный финансовый разбор текущего месяца по сравнению с прошлым: "
        "остатки по счетам, доходы и расходы, норма сбережений, темп бюджетов, главные риски и рекомендации."
    )
    await _prompt_response_format(message, prompt)


@router.message(StateFilter(AdvisorStates.chatting), F.text.in_(button_variants("🔍 На что я часто трачу?")))
async def quick_frequent_spending(message: Message) -> None:
    prompt = (
        "Oxirgi 90 kundagi xarajat odatlarimni tahlil qil: pul eng ko‘p qayerga ketyapti va "
        "operatsiyalar soni bo‘yicha eng tez-tez qilinadigan xarajatlar qaysilar (mayda muntazam xaridlar ham). "
        "Aniq summalar, chastota va tejash nuqtalarini ko‘rsat."
        if current_language.get() == "uz"
        else "Проанализируй мои привычки трат за последние 90 дней: куда уходит больше всего денег "
        "и на что я трачу чаще всего по количеству операций (включая мелкие регулярные траты). "
        "Покажи точные суммы, частоту и конкретные точки оптимизации."
    )
    await _prompt_response_format(message, prompt)


@router.message(StateFilter(AdvisorStates.chatting), F.text.in_(button_variants("💡 Проверить покупку")))
async def quick_purchase_prompt(message: Message) -> None:
    await message.answer(
        tr("💡 Напиши или скажи голосом, что и за сколько хочешь купить (и с какого счёта, если важно) — например:\n«Хочу купить телефон за 4 000 000 сум, стоит ли сейчас?»"),
        reply_markup=get_advisor_keyboard(),
    )


@router.message(StateFilter(AdvisorStates.chatting), F.content_type == ContentType.VOICE)
async def advisor_voice_question(
    message: Message,
    bot: Bot,
) -> None:
    """Transcribe voice messages inside advisor mode and ask preferred reply format."""
    with suppress(Exception):
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    file_info = await bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_file:
        temp_path = temp_file.name

    try:
        await bot.download_file(file_info.file_path, temp_path)
        transcribed_text = await speech_service.transcribe(temp_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    if not transcribed_text or transcribed_text.startswith("К сожалению"):
        await message.reply(
            tr("⚠️ Не удалось распознать голосовое сообщение. Попробуй сказать ещё раз или напиши текстом."),
            reply_markup=get_advisor_keyboard(),
        )
        return

    await message.reply(
        f"🎤 <i>{html.escape(transcribed_text)}</i>",
        parse_mode="HTML",
        reply_markup=get_advisor_keyboard(),
    )
    await _prompt_response_format(message, transcribed_text)


@router.message(StateFilter(AdvisorStates.chatting), F.text & ~F.text.startswith("/"))
async def advisor_text_question(message: Message) -> None:
    """Ask the user how they prefer the response before invoking LLM/TTS."""
    await _prompt_response_format(message, message.text or "")
