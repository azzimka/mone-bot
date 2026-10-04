import os
import tempfile
import logging
import uuid
from datetime import date, timezone, timedelta
from decimal import Decimal
from typing import Optional

from aiogram import Router, F, Bot
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.services.speech import SpeechService
from bot.services.ai_parser import AIParser
from bot.database.repositories import TransactionRepository, UserRepository
from bot.handlers.commands import fmt, get_main_keyboard

logger = logging.getLogger(__name__)
router = Router()

speech_service = SpeechService(api_key=settings.GROQ_API_KEY)
ai_parser = AIParser(api_key=settings.GROQ_API_KEY)

UZB_TZ = timezone(timedelta(hours=5))

# ─── FSM States ──────────────────────────────────────────────────────────────

class TopUpStates(StatesGroup):
    """Finite-state machine for the manual top-up flow."""
    waiting_for_amount = State()
    waiting_for_description = State()


class ReconcileStates(StatesGroup):
    """Finite-state machine for balance reconciliation."""
    waiting_for_amount = State()


def parse_balance_expression(text: str) -> Optional[int]:
    """
    Parses a direct number or a mathematical sum expression like:
    '50000', '50 000', '50к', '20000+15000+15000', '25k + 25k', '20 минг + 30 минг'
    """
    cleaned = text.lower().replace(" ", "").replace(",", "").replace("_", "")
    cleaned = cleaned.replace("тысяч", "000").replace("тыс", "000")
    cleaned = cleaned.replace("минг", "000").replace("ming", "000")
    cleaned = cleaned.replace("к", "000").replace("k", "000")
    cleaned = cleaned.replace("сум", "").replace("uzs", "").replace("som", "").replace("so'm", "")

    parts = cleaned.split("+")
    total = 0
    for p in parts:
        p = p.strip()
        if not p.isdigit():
            return None
        total += int(p)
    return total


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _get_balance_data(session: AsyncSession, user_id: int) -> dict:
    """
    Calculate the user's current balance from all transactions.
    Returns a dict with total_income, total_expenses, and balance.
    Never fetches all rows — uses DB-level aggregation for performance.
    """
    from datetime import date as date_type
    from sqlalchemy import select, func
    from bot.models.transaction import Transaction

    stmt_income = select(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).where(
        Transaction.user_id == user_id,
        Transaction.type == "income",
    )
    stmt_expense = select(
        func.coalesce(func.sum(Transaction.amount), 0)
    ).where(
        Transaction.user_id == user_id,
        Transaction.type == "expense",
    )

    income_result = await session.execute(stmt_income)
    expense_result = await session.execute(stmt_expense)

    total_income = Decimal(str(income_result.scalar() or 0))
    total_expenses = Decimal(str(expense_result.scalar() or 0))
    balance = total_income - total_expenses

    return {
        "total_income": total_income,
        "total_expenses": total_expenses,
        "balance": balance,
    }


def _balance_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard shown on the balance screen."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚖️ Сверить", callback_data="balance:reconcile"),
            InlineKeyboardButton(text="➕ Пополнить", callback_data="balance:topup"),
        ],
        [
            InlineKeyboardButton(text="📋 История", callback_data="balance:history:0"),
        ],
    ])


def _format_balance_message(data: dict, currency: str) -> str:
    """Format the main balance screen message."""
    balance = data["balance"]
    income = data["total_income"]
    expenses = data["total_expenses"]

    # Dynamically choose the status emoji based on balance level
    if balance <= 0:
        status = "🔴"
    elif balance < income * Decimal("0.1"):
        status = "🟡"
    else:
        status = "🟢"

    return (
        f"💰 *Текущий баланс*\n\n"
        f"{status} *{fmt(float(balance), currency)}*\n\n"
        f"├ 📥 Пополнения:  `{fmt(float(income), currency)}`\n"
        f"└ 📤 Расходы:      `{fmt(float(expenses), currency)}`"
    )


# ─── Balance screen ───────────────────────────────────────────────────────────

@router.message(F.text == "💰 Баланс")
@router.message(Command("balance"))
async def cmd_balance(message: Message, session: AsyncSession):
    """Show the main balance overview."""
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name,
    )

    data = await _get_balance_data(session, user.id)

    # First time: balance is zero and no income at all — prompt initial setup
    if data["total_income"] == 0 and data["total_expenses"] == 0:
        await message.answer(
            "💰 *Добро пожаловать в раздел Баланс!*\n\n"
            "Здесь ты можешь отслеживать свои деньги в реальном времени.\n\n"
            "Для начала *установи стартовый баланс* — сколько у тебя сейчас есть денег? "
            "Нажми «➕ Пополнить» и введи сумму.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="➕ Установить стартовый баланс", callback_data="balance:topup"),
            ]]),
        )
        return

    await message.answer(
        _format_balance_message(data, user.default_currency),
        parse_mode="Markdown",
        reply_markup=_balance_keyboard(),
    )


# ─── Top-up history ───────────────────────────────────────────────────────────

PAGE_SIZE = 10  # Transactions per page in history

@router.callback_query(F.data.startswith("balance:history:"))
async def cb_balance_history(callback: CallbackQuery, session: AsyncSession):
    """
    Show paginated income history, grouped by month.
    callback_data format: balance:history:<page>
    """
    page = int(callback.data.split(":")[2])

    user = await UserRepository.get_or_create(
        session, callback.from_user.id,
        callback.from_user.username, callback.from_user.first_name,
    )

    # Fetch income transactions, newest first
    from sqlalchemy import select
    from bot.models.transaction import Transaction

    stmt = (
        select(Transaction)
        .where(
            Transaction.user_id == user.id,
            Transaction.type == "income",
        )
        .order_by(Transaction.created_at.desc())
        .limit(PAGE_SIZE + 1)  # +1 to detect if there's a next page
        .offset(page * PAGE_SIZE)
    )
    result = await session.execute(stmt)
    txs = list(result.scalars().all())

    has_next = len(txs) > PAGE_SIZE
    txs = txs[:PAGE_SIZE]

    if not txs and page == 0:
        await callback.answer("Пополнений ещё нет.", show_alert=True)
        return

    # Group by month label
    month_names = [
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ]

    lines = ["📋 *История пополнений*\n"]
    current_month_label = None

    for tx in txs:
        dt = tx.created_at.astimezone(UZB_TZ)
        month_label = f"{month_names[dt.month - 1]} {dt.year}"

        if month_label != current_month_label:
            current_month_label = month_label
            lines.append(f"\n*{month_label}*")

        time_str = dt.strftime("%d.%m  %H:%M")
        desc = tx.description or tx.category or "Пополнение"
        amount_str = fmt(float(tx.amount), tx.currency)
        lines.append(f"`{time_str}`  +{amount_str}  _{desc}_")

    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="← Назад", callback_data=f"balance:history:{page - 1}"))
    if has_next:
        nav_buttons.append(InlineKeyboardButton(text="Дальше →", callback_data=f"balance:history:{page + 1}"))

    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="◀ К балансу", callback_data="balance:back")])

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


# ─── Top-up flow (FSM) ────────────────────────────────────────────────────────

@router.callback_query(F.data == "balance:topup")
async def cb_start_topup(callback: CallbackQuery, state: FSMContext):
    """Start the top-up FSM — ask for the amount."""
    await state.set_state(TopUpStates.waiting_for_amount)
    await callback.message.answer(
        "💵 *Введи сумму пополнения* (в сумах):\n\n"
        "_Например:_ `500000` или `1 500 000`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="balance:topup_cancel"),
        ]]),
    )
    await callback.answer()


@router.message(StateFilter(TopUpStates.waiting_for_amount))
async def fsm_topup_amount(message: Message, state: FSMContext):
    """Receive the top-up amount, ask for a description."""
    raw = message.text.strip().replace(" ", "").replace(",", "").replace(".", "")
    if not raw.isdigit():
        await message.answer(
            "⚠️ Введи только число, например: `150000`",
            parse_mode="Markdown",
        )
        return

    amount = int(raw)
    if amount <= 0:
        await message.answer("⚠️ Сумма должна быть больше нуля.")
        return

    await state.update_data(amount=amount)
    await state.set_state(TopUpStates.waiting_for_description)

    await message.answer(
        f"✅ Сумма: *{fmt(amount, 'UZS')}*\n\n"
        "📝 *Откуда эти деньги?* Напиши источник:\n"
        "_Например:_ Зарплата, От Дилноза, Фриланс...\n\n"
        "Или нажми «Пропустить»",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⏩ Пропустить", callback_data="balance:topup_nodesc"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="balance:topup_cancel"),
        ]]),
    )


@router.message(StateFilter(TopUpStates.waiting_for_description))
async def fsm_topup_description(message: Message, state: FSMContext, session: AsyncSession):
    """Receive the description and save the top-up transaction."""
    description = message.text.strip()
    data = await state.get_data()
    await _save_topup(message, session, state, data["amount"], description)


@router.callback_query(F.data == "balance:topup_nodesc")
async def cb_topup_nodesc(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Save top-up without a description."""
    data = await state.get_data()
    await _save_topup(callback.message, session, state, data["amount"], "Пополнение")
    await callback.answer()


@router.callback_query(F.data == "balance:topup_cancel")
async def cb_topup_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancel the top-up flow."""
    await state.clear()
    await callback.message.edit_text("❌ Пополнение отменено.")
    await callback.answer()


async def _save_topup(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    amount: int,
    description: str,
) -> None:
    """Internal: save income transaction and show updated balance."""
    user = await UserRepository.get_or_create(
        session, message.chat.id,
        None, None,
    )

    await TransactionRepository.create(
        session=session,
        user_id=user.id,
        type="income",
        amount=Decimal(str(amount)),
        currency=user.default_currency,
        category="Пополнение",
        description=description,
        date=date.today(),
    )

    await state.clear()

    # Show updated balance
    data = await _get_balance_data(session, user.id)

    await message.answer(
        f"✅ *+{fmt(amount, user.default_currency)}* добавлено к балансу!\n\n"
        + _format_balance_message(data, user.default_currency),
        parse_mode="Markdown",
        reply_markup=_balance_keyboard(),
    )


# ─── Back to balance ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "balance:back")
async def cb_balance_back(callback: CallbackQuery, session: AsyncSession):
    """Return to the main balance screen from a sub-screen."""
    user = await UserRepository.get_or_create(
        session, callback.from_user.id,
        callback.from_user.username, callback.from_user.first_name,
    )
    data = await _get_balance_data(session, user.id)

    await callback.message.edit_text(
        _format_balance_message(data, user.default_currency),
        parse_mode="Markdown",
        reply_markup=_balance_keyboard(),
    )
    await callback.answer()


# ─── Reconciliation flow (FSM) ──────────────────────────────────────────────

@router.callback_query(F.data == "balance:reconcile")
async def cb_start_reconcile(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Start balance reconciliation flow."""
    user = await UserRepository.get_or_create(
        session, callback.from_user.id,
        callback.from_user.username, callback.from_user.first_name,
    )
    data = await _get_balance_data(session, user.id)
    curr_str = fmt(float(data["balance"]), user.default_currency)

    await state.set_state(ReconcileStates.waiting_for_amount)
    await callback.message.answer(
        f"⚖️ *Сверка баланса*\n\n"
        f"В боте сейчас: *{curr_str}*\n\n"
        "Сколько у тебя сейчас денег суммарно на всех картах и в кармане?\n"
        "Введи число или напиши сумму через плюс:\n"
        "_Например:_ `50000` или `25000 + 15000 + 10000`\n\n"
        "_(также можешь отправить голосовое сообщение)_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="balance:reconcile_cancel"),
        ]]),
    )
    await callback.answer()


@router.callback_query(F.data == "balance:reconcile_cancel")
async def cb_reconcile_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancel reconciliation."""
    await state.clear()
    await callback.message.edit_text("❌ Сверка баланса отменена.")
    await callback.answer()


@router.message(StateFilter(ReconcileStates.waiting_for_amount), F.text)
async def fsm_reconcile_amount(message: Message, state: FSMContext, session: AsyncSession):
    """Handle text input for target balance."""
    raw = message.text.strip()
    target = parse_balance_expression(raw)

    if target is None:
        parsed = await ai_parser.parse(raw, "UZS")
        if parsed and parsed.transactions:
            target = int(parsed.transactions[0].amount)

    if target is None or target < 0:
        await message.answer(
            "⚠️ Не удалось распознать сумму.\n\n"
            "Введи число (например `50000`) или сложение (`20000 + 30000`), либо нажми «Отмена»:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="❌ Отмена", callback_data="balance:reconcile_cancel"),
            ]]),
        )
        return

    await _apply_reconciliation(message, session, state, target)


@router.message(StateFilter(ReconcileStates.waiting_for_amount), F.voice)
async def fsm_reconcile_voice(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    """Handle voice input during reconciliation."""
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
    voice = message.voice
    file_info = await bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_file:
        temp_path = temp_file.name

    try:
        await bot.download_file(file_info.file_path, temp_path)
        transcribed_text = await speech_service.transcribe(temp_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    if not transcribed_text or transcribed_text.startswith("К сожалению"):
        await message.reply("⚠️ Не удалось разобрать голос. Попробуйте написать текстом.")
        return

    await message.reply(f"🎤 *Распознано:* _{transcribed_text}_", parse_mode="Markdown")

    target = parse_balance_expression(transcribed_text)
    if target is None:
        parsed = await ai_parser.parse(transcribed_text, "UZS")
        if parsed and parsed.transactions:
            target = int(parsed.transactions[0].amount)

    if target is None or target < 0:
        await message.answer(
            "⚠️ Не удалось определить сумму из голоса. Попробуйте сказать, например: «50 тысяч» или напишите число текстом."
        )
        return

    await _apply_reconciliation(message, session, state, target)


async def _apply_reconciliation(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    target_amount: int,
) -> None:
    """Internal: apply balance reconciliation, save diff transaction, and show result."""
    user = await UserRepository.get_or_create(
        session, message.chat.id, None, None
    )

    data = await _get_balance_data(session, user.id)
    curr_balance = data["balance"]
    target_decimal = Decimal(str(target_amount))
    diff = target_decimal - curr_balance
    currency = user.default_currency

    if diff > 0:
        diff_fmt = f"{float(diff):,.0f}".replace(",", " ")
        await TransactionRepository.create(
            session=session,
            user_id=user.id,
            type="income",
            amount=diff,
            currency=currency,
            category="Сверка",
            description=f"Сверка (+{diff_fmt} {currency})",
            date=date.today(),
        )
        diff_str = f"+{diff_fmt} {currency} (доход)"
    elif diff < 0:
        abs_diff = abs(diff)
        abs_diff_fmt = f"{float(abs_diff):,.0f}".replace(",", " ")
        await TransactionRepository.create(
            session=session,
            user_id=user.id,
            type="expense",
            amount=abs_diff,
            currency=currency,
            category="Сверка",
            description=f"Сверка (-{abs_diff_fmt} {currency})",
            date=date.today(),
        )
        diff_str = f"-{abs_diff_fmt} {currency} (расход)"
    else:
        diff_str = f"0 {currency} (без изменений)"

    await state.clear()

    new_data = await _get_balance_data(session, user.id)
    curr_fmt = f"{float(curr_balance):,.0f}".replace(",", " ")
    target_fmt = f"{float(target_decimal):,.0f}".replace(",", " ")

    status_icon = "🟢" if target_decimal > 0 else "🔴"

    await message.answer(
        f"⚖️ *Баланс успешно сверен!*\n\n"
        f"├ Было в боте:  `{curr_fmt} {currency}`\n"
        f"├ Разница:      *{diff_str}*\n"
        f"└ Стало:        *{target_fmt} {currency}* {status_icon}\n\n"
        + _format_balance_message(new_data, currency),
        parse_mode="Markdown",
        reply_markup=_balance_keyboard(),
    )
