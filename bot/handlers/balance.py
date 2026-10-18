from bot.services.finance import local_today, balance_totals, owned_account
from bot.services.i18n import tr, button_variants, current_language
import os
import tempfile
import logging
import re
from datetime import timezone
from zoneinfo import ZoneInfo
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
from bot.services.csv_import import CsvImportError, parse_amount, MAX_AMOUNT

logger = logging.getLogger(__name__)
router = Router()

speech_service = SpeechService(api_key=settings.GROQ_API_KEY)
ai_parser = AIParser(api_key=settings.GROQ_API_KEY)

# ─── FSM States ──────────────────────────────────────────────────────────────

class TopUpStates(StatesGroup):
    """Finite-state machine for the manual top-up flow."""
    waiting_for_amount = State()
    waiting_for_description = State()


class ReconcileStates(StatesGroup):
    """Finite-state machine for balance reconciliation."""
    waiting_for_amount = State()


def parse_balance_expression(text: str, currency: str = "UZS") -> Optional[Decimal]:
    """Parse exact decimal sums; never erase or reinterpret a foreign currency."""
    cleaned = text.lower().replace("_", "").replace("’", "'").strip()
    aliases = {"UZS": ("uzs", "so'm", "som", "sum", "сум", "сўм"),
               "USD": ("usd", "доллар", "dollar", "$"), "EUR": ("eur", "евро", "yevro", "€")}
    for alias in sorted(aliases.get(currency.upper(), (currency.lower(),)), key=len, reverse=True):
        cleaned = cleaned.replace(alias, "")
    total = Decimal(0)
    for part in cleaned.split("+"):
        part = part.strip()
        multiplier = Decimal(1)
        suffix = re.search(r"(?:тысяч|тыс|минг|ming|к|k)$", part)
        if suffix:
            multiplier = Decimal(1000)
            part = part[:suffix.start()]
        try:
            value = parse_amount(part) * multiplier
        except CsvImportError:
            return None
        if value < 0 or value > MAX_AMOUNT:
            return None
        total += value
    return total if total <= MAX_AMOUNT else None


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _get_balance_data(session: AsyncSession, user_id: int, currency: str | None = None, account_id: int | None = None) -> dict:
    from bot.models import User
    user = await session.get(User, user_id)
    return await balance_totals(session, user, currency, account_id)


def _balance_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard shown on the balance screen."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=tr('⚖️ Сверить'), callback_data="balance:reconcile"),
            InlineKeyboardButton(text=tr('➕ Пополнить'), callback_data="balance:topup"),
        ],
        [
            InlineKeyboardButton(text=tr('📋 История'), callback_data="balance:history:0"),
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
        tr('💰 *Текущий баланс*\n\n{p1} *{p3}*\n\n├ 📥 Пополнения:  `{p5}`\n└ 📤 Расходы:      `{p7}`' ,p1=f'{status}', p3=f'{fmt(balance, currency)}', p5=f'{fmt(income, currency)}', p7=f'{fmt(expenses, currency)}')
    )


# ─── Balance screen ───────────────────────────────────────────────────────────

@router.message(F.text.in_(button_variants('💰 Баланс')))
@router.message(Command("balance"))
async def cmd_balance(message: Message, session: AsyncSession):
    """Show the main balance overview."""
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name,
    )

    data = await _get_balance_data(session, user.id)

    # First time: balance is zero and no income at all — prompt initial setup
    if data["total_income"] == 0 and data["total_expenses"] == 0 and data["balance"] == 0:
        await message.answer(
            tr('💰 *Добро пожаловать в раздел Баланс!*\n\nЗдесь ты можешь отслеживать свои деньги в реальном времени.\n\nДля начала *установи стартовый баланс* — сколько у тебя сейчас есть денег? Нажми «➕ Пополнить» и введи сумму.'),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=tr('➕ Установить стартовый баланс'), callback_data="balance:topup"),
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
    page_value = callback.data.split(":")[2]
    if not page_value.isdigit():
        await callback.answer()
        return
    page = int(page_value)

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
            Transaction.currency == user.default_currency,
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
        await callback.answer(tr('Пополнений ещё нет.'), show_alert=True)
        return

    # Group by month label
    month_names = [
        tr('Январь'), tr('Февраль'), tr('Март'), tr('Апрель'), tr('Май'), tr('Июнь'),
        tr('Июль'), tr('Август'), tr('Сентябрь'), tr('Октябрь'), tr('Ноябрь'), tr('Декабрь'),
    ]

    lines = [tr('📋 *История пополнений*\n')]
    current_month_label = None

    for tx in txs:
        stamp = tx.created_at if tx.created_at.tzinfo else tx.created_at.replace(tzinfo=timezone.utc)
        dt = stamp.astimezone(ZoneInfo(user.timezone or "Asia/Tashkent"))
        month_label = f"{month_names[dt.month - 1]} {dt.year}"

        if month_label != current_month_label:
            current_month_label = month_label
            lines.append(f"\n*{month_label}*")

        time_str = dt.strftime("%d.%m  %H:%M")
        desc = tx.description or tx.category or "Пополнение"
        amount_str = fmt(tx.amount, tx.currency)
        lines.append(f"`{time_str}`  +{amount_str}  _{desc}_")

    # Pagination buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text=tr('← Назад'), callback_data=f"balance:history:{page - 1}"))
    if has_next:
        nav_buttons.append(InlineKeyboardButton(text=tr('Дальше →'), callback_data=f"balance:history:{page + 1}"))

    keyboard = []
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text=tr('◀ К балансу'), callback_data="balance:back")])

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
    )
    await callback.answer()


# ─── Top-up flow (FSM) ────────────────────────────────────────────────────────

@router.callback_query(F.data == "balance:topup")
async def cb_start_topup(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Start the top-up FSM — ask for the amount."""
    user = await UserRepository.get_or_create(session, callback.from_user.id)
    account = await owned_account(session, user, None, user.default_currency)
    await state.clear()
    await state.update_data(user_id=user.id, currency=account.currency, account_id=account.id)
    await state.set_state(TopUpStates.waiting_for_amount)
    await callback.message.answer(
        (f"💵 Kirim summasi ({account.currency})\n💳 {account.name}\nMasalan: 500 yoki 500.50" if current_language.get() == "uz" else f"💵 Сумма пополнения ({account.currency})\n💳 {account.name}\nНапример: 500 или 500.50"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=tr('❌ Отмена'), callback_data="balance:topup_cancel"),
        ]]),
    )
    await callback.answer()


@router.message(StateFilter(TopUpStates.waiting_for_amount))
async def fsm_topup_amount(message: Message, state: FSMContext):
    """Receive the top-up amount, ask for a description."""
    data = await state.get_data()
    currency = data.get("currency")
    amount = parse_balance_expression(message.text or "", currency or "UZS")
    if currency is None or amount is None:
        await message.answer(
            tr('⚠️ Введи только число, например: `150000`'),
            parse_mode="Markdown",
        )
        return

    if amount <= 0:
        await message.answer(tr('⚠️ Сумма должна быть больше нуля.'))
        return

    # MemoryStorage can store Decimal, but strings also work with JSON stores.
    await state.update_data(amount=str(amount))
    await state.set_state(TopUpStates.waiting_for_description)

    await message.answer(
        tr('✅ Сумма: *{p1}*\n\n📝 *Откуда эти деньги?* Напиши источник:\n_Например:_ Зарплата, От Дилноза, Фриланс...\n\nИли нажми «Пропустить»' ,p1=f"{fmt(amount, currency)}"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=tr('⏩ Пропустить'), callback_data="balance:topup_nodesc"),
            InlineKeyboardButton(text=tr('❌ Отмена'), callback_data="balance:topup_cancel"),
        ]]),
    )


@router.message(StateFilter(TopUpStates.waiting_for_description))
async def fsm_topup_description(message: Message, state: FSMContext, session: AsyncSession):
    """Receive the description and save the top-up transaction."""
    if not message.text or len(message.text) > 2000:
        await message.answer("Izohni matnda yozing (2000 belgigacha)." if current_language.get() == "uz" else "Напишите описание текстом (до 2000 символов).")
        return
    description = message.text.strip()
    data = await state.get_data()
    await _save_topup(message, session, state, data["amount"], description)


@router.callback_query(F.data == "balance:topup_nodesc")
async def cb_topup_nodesc(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Save top-up without a description."""
    data = await state.get_data()
    if "amount" not in data or "user_id" not in data:
        await callback.answer(tr('❌ Данная операция уже обработана или устарела.'), show_alert=True)
        return
    await _save_topup(callback.message, session, state, data["amount"], "Пополнение")
    await callback.answer()


@router.callback_query(F.data == "balance:topup_cancel")
async def cb_topup_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancel the top-up flow."""
    await state.clear()
    await callback.message.edit_text(tr('❌ Пополнение отменено.'))
    await callback.answer()


async def _save_topup(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    amount: Decimal | str,
    description: str,
) -> None:
    """Internal: save income transaction and show updated balance."""
    from bot.models import User
    flow = await state.get_data()
    user = await session.get(User, flow["user_id"])
    account = await owned_account(session, user, flow["account_id"], flow["currency"])

    await TransactionRepository.create(
        session=session,
        user_id=user.id,
        account_id=account.id,
        type="income",
        amount=Decimal(str(amount)),
        currency=account.currency,
        category="Пополнение",
        description=description,
        date=local_today(user),
    )

    await state.clear()

    # Show updated balance
    data = await _get_balance_data(session, user.id, account.currency)

    await message.answer(
        tr('✅ *+{p1}* добавлено к балансу!\n\n' ,p1=f'{fmt(amount, account.currency)}')
        + _format_balance_message(data, account.currency),
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
    account = await owned_account(session, user, None, user.default_currency)
    data = await _get_balance_data(session, user.id, account.currency, account.id)
    curr_str = fmt(data["balance"], account.currency)

    await state.clear()
    await state.update_data(user_id=user.id, currency=account.currency, account_id=account.id)
    await state.set_state(ReconcileStates.waiting_for_amount)
    await callback.message.answer(
        (f"⚖️ Balansni tenglashtirish\n💳 Faqat hisob: {account.name}\nHozir: {curr_str}\n\nShu hisobdagi haqiqiy summani kiriting.\nMasalan: 500 yoki 250.50 + 100" if current_language.get() == "uz" else f"⚖️ Сверка баланса\n💳 Только счёт: {account.name}\nСейчас: {curr_str}\n\nВведите фактическую сумму на этом счёте.\nНапример: 500 или 250.50 + 100"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=tr('❌ Отмена'), callback_data="balance:reconcile_cancel"),
        ]]),
    )
    await callback.answer()


@router.callback_query(F.data == "balance:reconcile_cancel")
async def cb_reconcile_cancel(callback: CallbackQuery, state: FSMContext):
    """Cancel reconciliation."""
    await state.clear()
    await callback.message.edit_text(tr('❌ Сверка баланса отменена.'))
    await callback.answer()


@router.message(StateFilter(ReconcileStates.waiting_for_amount), F.text)
async def fsm_reconcile_amount(message: Message, state: FSMContext, session: AsyncSession):
    """Handle text input for target balance."""
    raw = message.text.strip()
    flow = await state.get_data()
    currency = flow.get("currency")
    if currency is None:
        await state.clear()
        await message.answer(tr('❌ Данная операция уже обработана или устарела.'))
        return
    target = parse_balance_expression(raw, currency)

    if target is None and not raw.lstrip().startswith("-"):
        parsed = await ai_parser.parse(f"Сверка баланса: {raw}", currency)
        if parsed and len(parsed.transactions) == 1 and parsed.transactions[0].type == "reconcile" and parsed.transactions[0].currency == currency:
            target = Decimal(str(parsed.transactions[0].amount))

    if target is None or target < 0:
        await message.answer(
            tr('⚠️ Не удалось распознать сумму.\n\nВведи число (например `50000`) или сложение (`20000 + 30000`), либо нажми «Отмена»:'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=tr('❌ Отмена'), callback_data="balance:reconcile_cancel"),
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
        await message.reply(tr('⚠️ Не удалось разобрать голос. Попробуйте написать текстом.'))
        return

    await message.reply(tr('🎤 *Распознано:* _{p1}_' ,p1=f'{transcribed_text}'), parse_mode="Markdown")

    flow = await state.get_data()
    currency = flow.get("currency")
    if currency is None:
        await state.clear()
        await message.answer(tr('❌ Данная операция уже обработана или устарела.'))
        return
    target = parse_balance_expression(transcribed_text, currency)
    if target is None and not transcribed_text.lstrip().startswith("-"):
        parsed = await ai_parser.parse(f"Сверка баланса: {transcribed_text}", currency)
        if parsed and len(parsed.transactions) == 1 and parsed.transactions[0].type == "reconcile" and parsed.transactions[0].currency == currency:
            target = Decimal(str(parsed.transactions[0].amount))

    if target is None or target < 0:
        await message.answer(
            tr('⚠️ Не удалось определить сумму из голоса. Попробуйте сказать, например: «50 тысяч» или напишите число текстом.')
        )
        return

    await _apply_reconciliation(message, session, state, target)


async def _apply_reconciliation(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    target_amount: Decimal,
) -> None:
    """Internal: apply balance reconciliation, save diff transaction, and show result."""
    from bot.models import User
    flow = await state.get_data()
    user = await session.get(User, flow["user_id"])
    account = await owned_account(session, user, flow["account_id"], flow["currency"])
    data = await _get_balance_data(session, user.id, account.currency, account.id)
    curr_balance = data["balance"]
    target_decimal = Decimal(str(target_amount))
    diff = target_decimal - curr_balance
    currency = account.currency

    if diff > 0:
        diff_fmt = fmt(diff, currency).rsplit(" ", 1)[0]
        await TransactionRepository.create(
            session=session,
            user_id=user.id,
            account_id=account.id,
            type="income",
            amount=diff,
            currency=currency,
            category="Сверка",
            description=f"Сверка (+{diff_fmt} {currency})",
            date=local_today(user),
        )
        diff_str = tr('+{p1} {p3} (доход)' ,p1=f'{diff_fmt}', p3=f'{currency}')
    elif diff < 0:
        abs_diff = abs(diff)
        abs_diff_fmt = fmt(abs_diff, currency).rsplit(" ", 1)[0]
        await TransactionRepository.create(
            session=session,
            user_id=user.id,
            account_id=account.id,
            type="expense",
            amount=abs_diff,
            currency=currency,
            category="Сверка",
            description=f"Сверка (-{abs_diff_fmt} {currency})",
            date=local_today(user),
        )
        diff_str = tr('-{p1} {p3} (расход)' ,p1=f'{abs_diff_fmt}', p3=f'{currency}')
    else:
        diff_str = tr('0 {p1} (без изменений)' ,p1=f'{currency}')

    await state.clear()

    new_data = await _get_balance_data(session, user.id, currency, account.id)
    curr_fmt = fmt(curr_balance, currency).rsplit(" ", 1)[0]
    target_fmt = fmt(target_decimal, currency).rsplit(" ", 1)[0]

    status_icon = "🟢" if target_decimal > 0 else "🔴"

    await message.answer(
        tr('⚖️ *Баланс успешно сверен!*\n\n├ Было в боте:  `{p1} {p3}`\n├ Разница:      *{p5}*\n└ Стало:        *{p7} {p9}* {p11}\n\n' ,p1=f'{curr_fmt}', p3=f'{currency}', p5=f'{diff_str}', p7=f'{target_fmt}', p9=f'{currency}', p11=f'{status_icon}')
        + _format_balance_message(new_data, currency),
        parse_mode="Markdown",
        reply_markup=_balance_keyboard(),
    )
