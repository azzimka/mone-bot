"""Telegram calendar and reports based on the dates stored in the ledger."""

from calendar import monthrange
from collections import defaultdict
from datetime import date, timezone
from decimal import Decimal
from html import escape
from typing import Literal
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.repositories import CATEGORY_ICON_MAP, TransactionRepository
from bot.handlers.commands import fmt, get_main_keyboard
from bot.models import User
from bot.services.finance import local_today
from bot.services.i18n import button_variants, category_label, tr

router = Router()
MONTH_NAMES = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
PAGE_SIZE = 12


class HistoryAction(CallbackData, prefix="expenses"):
    view: Literal["period", "months_day", "months_total", "days", "day", "month"]
    year: int = 0
    month: int = 0
    day: int = 0
    page: int = 0


def button(label: str, action: HistoryAction, *, today: bool = False) -> InlineKeyboardButton:
    # aiogram 3.15 forwards extra button fields to Telegram.
    style = {"style": "primary"} if today else {}
    return InlineKeyboardButton(text=label, callback_data=action.pack(), **style)


def period_menu() -> tuple[str, InlineKeyboardMarkup]:
    return tr("За какой период показать расходы?"), InlineKeyboardMarkup(inline_keyboard=[[
        button(f"☀️ {tr('За день')}", HistoryAction(view="months_day")),
        button(f"🗓️ {tr('За месяц')}", HistoryAction(view="months_total")),
    ]])


def month_menu(view: Literal["months_day", "months_total"], year: int, today: date):
    next_view = "days" if view == "months_day" else "month"
    months = [
        button(tr(name), HistoryAction(view=next_view, year=year, month=month))
        for month, name in enumerate(MONTH_NAMES, start=1)
    ]
    rows = [months[i:i + 3] for i in range(0, len(months), 3)]
    years = []
    if year > 1:
        years.append(button(f"‹ {year - 1}", HistoryAction(view=view, year=year - 1)))
    if year < today.year:
        years.append(button(f"{year + 1} ›", HistoryAction(view=view, year=year + 1)))
    if years:
        rows.append(years)
    rows.append([button(tr("← Назад"), HistoryAction(view="period"))])
    return tr("Выберите месяц · {year}", year=year), InlineKeyboardMarkup(inline_keyboard=rows)


def day_menu(month: date, today: date):
    days = []
    for day in range(1, monthrange(month.year, month.month)[1] + 1):
        is_today = month.replace(day=day) == today
        days.append(button(
            f"🔹 {day}" if is_today else str(day),
            HistoryAction(view="day", year=month.year, month=month.month, day=day),
            today=is_today,
        ))
    rows = [days[i:i + 6] for i in range(0, len(days), 6)]
    rows.append([button(tr("← Назад"), HistoryAction(view="months_day", year=month.year))])
    month_label = f"{tr(MONTH_NAMES[month.month - 1])} {month.year}"
    return tr("Выберите день · {month}", month=month_label), InlineKeyboardMarkup(inline_keyboard=rows)


async def day_report(session: AsyncSession, user: User, day: date):
    expenses = await TransactionRepository.get_by_period(
        session, user.id, day, day, tx_type="expense", all_currencies=True,
    )
    user_timezone = ZoneInfo(user.timezone or "Asia/Tashkent")
    lines = []
    totals = defaultdict(Decimal)
    for expense in expenses:
        category = expense.category or "Другое"
        icon = CATEGORY_ICON_MAP.get(category, "❓")
        label = (expense.description or "").strip() or category_label(category)
        stamp = expense.created_at
        stamp = (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).astimezone(user_timezone)
        time_label = f"<code>{stamp:%H:%M}</code> " if stamp.date() == day else ""
        amount = escape(fmt(expense.amount, expense.currency))
        lines.append(f"{time_label}{icon} {short_label(label)} — <b>{amount}</b>")
        totals[expense.currency] += expense.amount
    return lines, totals


async def month_report(session: AsyncSession, user: User, month: date):
    last_day = month.replace(day=monthrange(month.year, month.month)[1])
    groups = await TransactionRepository.get_expenses_by_category_and_currency(session, user.id, month, last_day)
    lines = []
    totals = defaultdict(Decimal)
    for category, currency, amount in groups:
        icon = CATEGORY_ICON_MAP.get(category, "❓")
        lines.append(f"{icon} {short_label(category_label(category))} — <b>{escape(fmt(amount, currency))}</b>")
        totals[currency] += amount
    return lines, totals


def short_label(label: str) -> str:
    label = " ".join(label.split())
    return escape(label if len(label) <= 120 else label[:119] + "…")


async def report_view(session: AsyncSession, user: User, selected: date, action: HistoryAction):
    if action.view == "day":
        lines, totals = await day_report(session, user, selected)
        period = selected.strftime("%d.%m.%Y")
        back = HistoryAction(view="days", year=selected.year, month=selected.month)
    else:
        lines, totals = await month_report(session, user, selected)
        period = f"{tr(MONTH_NAMES[selected.month - 1])} {selected.year}"
        back = HistoryAction(view="months_total", year=selected.year)

    pages = max(1, (len(lines) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(action.page, pages - 1)
    start = page * PAGE_SIZE
    title = tr("📋 Расходы за {period}", period=period)
    text = [f"<b>{title}</b>", ""]
    rows = []
    if lines:
        text.extend(lines[start:start + PAGE_SIZE])
        total = " · ".join(fmt(amount, currency) for currency, amount in sorted(totals.items()))
        text.extend(["", f"<b>{tr('Итого')}: {escape(total)}</b>"])
        if pages > 1:
            text.append(tr("Страница {page} из {pages}", page=page + 1, pages=pages))
            navigation = []
            if page > 0:
                navigation.append(button(tr("← Назад"), action.model_copy(update={"page": page - 1})))
            if page < pages - 1:
                navigation.append(button(tr("Дальше →"), action.model_copy(update={"page": page + 1})))
            rows.append(navigation)
    else:
        text.append(tr("Расходов нет."))
    label = "📅 Выбрать день" if action.view == "day" else "📅 Выбрать месяц"
    rows.append([button(tr(label), back)])
    return "\n".join(text), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.chat.type == "private", F.text.in_(button_variants("📅 История расходов")))
@router.message(F.chat.type == "private", Command("history"))
async def cmd_history(message: Message):
    text, keyboard = period_menu()
    await message.answer(text, reply_markup=keyboard)


@router.message(F.text.in_(button_variants("📋 Расходы за сегодня")))
@router.message(Command("today"))
async def cmd_today(message: Message, mone_user: User, session: AsyncSession):
    today = local_today(mone_user)
    action = HistoryAction(view="day", year=today.year, month=today.month, day=today.day)
    text, keyboard = await report_view(session, mone_user, today, action)
    reply_markup = keyboard if message.chat.type == "private" and len(keyboard.inline_keyboard) > 1 else get_main_keyboard()
    await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


@router.message(F.chat.type == "private", F.text.in_(button_variants("📅 Расходы за месяц")))
@router.message(F.chat.type == "private", Command("month"))
async def cmd_month(message: Message, mone_user: User):
    today = local_today(mone_user)
    text, keyboard = month_menu("months_total", today.year, today)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(HistoryAction.filter())
async def navigate_history(callback: CallbackQuery, callback_data: HistoryAction, mone_user: User, session: AsyncSession):
    message = callback.message
    if not isinstance(message, Message) or message.chat.type != "private" or message.chat.id != callback.from_user.id:
        await callback.answer()
        return

    today = local_today(mone_user)
    action = callback_data
    year = action.year or today.year
    try:
        if not 1 <= year <= today.year or action.page < 0:
            raise ValueError
        if action.view in {"days", "day", "month"}:
            selected = date(year, action.month, action.day if action.view == "day" else 1)
    except ValueError:
        await callback.answer(tr("Некорректная дата."))
        return

    await callback.answer()
    if action.view == "period":
        text, keyboard = period_menu()
    elif action.view in {"months_day", "months_total"}:
        text, keyboard = month_menu(action.view, year, today)
    elif action.view == "days":
        text, keyboard = day_menu(selected, today)
    else:
        text, keyboard = await report_view(session, mone_user, selected, action)

    try:
        await message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "message is not modified" not in error.message.lower():
            raise


@router.callback_query(F.data.regexp(r"^month_report:[0-9]{4}-[0-9]{2}$"))
async def open_legacy_month(callback: CallbackQuery, mone_user: User, session: AsyncSession):
    year, month = map(int, callback.data.removeprefix("month_report:").split("-"))
    await navigate_history(callback, HistoryAction(view="month", year=year, month=month), mone_user, session)
