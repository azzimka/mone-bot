import logging
from datetime import date, timedelta
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.repositories import UserRepository, CategoryRepository, TransactionRepository, CATEGORY_ICON_MAP
from bot.models.transaction import Transaction
from bot.models.csv_import import CsvImport

logger = logging.getLogger(__name__)
router = Router()

# Russian day names
WEEKDAY_NAMES = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Build the persistent reply keyboard with main action buttons."""
    rows = []
    if settings.WEB_PUBLIC_URL:
        rows.append([
            KeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=settings.WEB_PUBLIC_URL)),
        ])
    rows.extend([
        [
            KeyboardButton(text="📊 Расходы за неделю"),
            KeyboardButton(text="📋 Расходы за сегодня"),
        ],
        [
            KeyboardButton(text="💰 Баланс"),
            KeyboardButton(text="📅 Расходы за месяц"),
        ],
        [
            KeyboardButton(text="🚌 Автобус / Метро — 2 000 сум"),
        ],
    ])
    keyboard = ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        persistent=True,
    )
    return keyboard


def fmt(amount: float, currency: str = "UZS") -> str:
    """Format amount with space separator."""
    return f"{amount:,.0f}".replace(",", " ") + f" {currency}"


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession):
    """Handle /start command, register user and seed defaults."""
    user = await UserRepository.get_or_create(
        session=session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    await CategoryRepository.seed_defaults(session)

    welcome_text = (
        f"👋 Привет, {message.from_user.first_name or 'друг'}!\n\n"
        "Я *Mone* — твой личный финансовый помощник.\n\n"
        "Просто скажи мне голосом или напиши:\n"
        "• «Кофе 25 тысяч»\n"
        "• «Такси 15к»\n"
        "• «Обед 80000»\n\n"
        "Я запишу трату, и ты всегда сможешь посмотреть статистику. 📊"
    )
    inline_kb = None
    if settings.WEB_PUBLIC_URL:
        inline_kb = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(text="🚀 Открыть Mone Mini App", web_app=WebAppInfo(url=settings.WEB_PUBLIC_URL)),
            ]]
        )

    await message.answer(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )
    if inline_kb:
        await message.answer(
            "📱 Также ты можешь открыть интерактивный финансовый кабинет:",
            reply_markup=inline_kb,
        )


@router.message(Command("app"))
async def cmd_app(message: Message):
    """Open WebApp Mini App."""
    if not settings.WEB_PUBLIC_URL:
        await message.answer("Веб-приложение пока не настроено.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="🚀 Открыть Mone Mini App", web_app=WebAppInfo(url=settings.WEB_PUBLIC_URL)),
        ]]
    )
    await message.answer("Нажми кнопку ниже, чтобы открыть финансовый кабинет прямо в Telegram:", reply_markup=kb)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Detailed help message."""
    help_text = (
        "📖 *Как пользоваться Mone*\n\n"
        "Отправь голосовое или текстовое сообщение:\n"
        "• «Купил продукты на 150 тысяч»\n"
        "• «Заплатил за интернет 100000»\n"
        "• «Такси 15к и кофе 25к»\n\n"
        "*Кнопки:*\n"
        "📋 *Расходы за сегодня* — подробный список трат за день\n"
        "📊 *Расходы за неделю* — сколько потрачено каждый день\n"
        "🚌 *Автобус / Метро* — мгновенно записывает 2 000 сум\n\n"
        "Если бот ошибётся — нажми ❌ под сообщением."
        "\n\n/import — импорт расходов и доходов из CSV."
    )
    await message.answer(help_text, parse_mode="Markdown", reply_markup=get_main_keyboard())


@router.message(F.text == "🚌 Автобус / Метро — 2 000 сум")
async def cmd_quick_transport(message: Message, session: AsyncSession):
    """Instantly record a fixed 2000 UZS public transport expense."""
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name
    )

    await TransactionRepository.create(
        session=session,
        user_id=user.id,
        type="expense",
        amount=2000,
        currency=user.default_currency,
        category="Транспорт",
        description="Автобус / Метро",
        voice_text=None,
        date=date.today(),
    )

    # Count how many times used today
    today_txs = await TransactionRepository.get_by_period(
        session, user.id, date.today(), date.today(), tx_type="expense"
    )
    transport_today = sum(
        1 for t in today_txs
        if t.description == "Автобус / Метро"
    )

    await message.answer(
        f"🚌 *2 000 {user.default_currency}* — записано!\n"
        f"_Транспорт сегодня: {transport_today} раз · "
        f"{fmt(transport_today * 2000, user.default_currency)}_",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


@router.message(F.text == "📋 Расходы за сегодня")
@router.message(Command("today"))
async def cmd_today(message: Message, session: AsyncSession):
    """Detailed today's expense report — every transaction + total."""
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name
    )

    today = date.today()
    transactions = await TransactionRepository.get_by_period(
        session, user.id, today, today, tx_type="expense"
    )
    total = float(await TransactionRepository.get_total(
        session, user.id, today, today, "expense"
    ))

    if not transactions:
        await message.answer(
            f"📋 *{today.strftime('%d.%m.%Y')} — расходов нет*\n\n"
            "Скажи мне голосом или напиши, на что потратил деньги 🎤",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(),
        )
        return

    from datetime import timezone, timedelta
    uzb_tz = timezone(timedelta(hours=5))
    
    lines = [f"📋 *Расходы за {today.strftime('%d.%m.%Y')}*\n"]
    for tx in transactions:
        icon = CATEGORY_ICON_MAP.get(tx.category or "Другое", "❓")
        amount_str = fmt(float(tx.amount), tx.currency)
        desc = tx.description or tx.category or "—"
        
        # Format time to UTC+5 (Uzbekistan)
        time_str = tx.created_at.astimezone(uzb_tz).strftime("%H:%M")
        
        lines.append(f"`{time_str}` {icon} {desc} — *{amount_str}*")

    lines.append(f"\n💸 *Итого: {fmt(total, user.default_currency)}*")

    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


@router.message(F.text == "📊 Расходы за неделю")
@router.message(Command("week"))
async def cmd_week(message: Message, session: AsyncSession):
    """Weekly expense report — daily breakdown for last 7 days."""
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name
    )

    today = date.today()
    week_ago = today - timedelta(days=6)  # Last 7 days including today

    # Get daily totals
    daily_totals = await TransactionRepository.get_daily_totals(
        session, user.id, week_ago, today, tx_type="expense"
    )
    total_week = float(await TransactionRepository.get_total(
        session, user.id, week_ago, today, "expense"
    ))

    if not daily_totals:
        await message.answer(
            "📊 *Расходы за неделю*\n\nЗа последние 7 дней расходов нет.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(),
        )
        return

    # Build a dict of all days in range
    daily_dict: dict[date, float] = {}
    for d in range(7):
        day = week_ago + timedelta(days=d)
        daily_dict[day] = 0.0
    for tx_date, amount in daily_totals:
        daily_dict[tx_date] = float(amount)

    # Find max for bar scaling
    max_amount = max(daily_dict.values()) if daily_dict.values() else 1

    lines = ["📊 *Расходы за последние 7 дней*\n"]
    for day, amount in sorted(daily_dict.items()):
        day_name = WEEKDAY_NAMES[day.weekday()]
        date_str = day.strftime("%d.%m")
        is_today = "← сегодня" if day == today else ""

        if amount > 0:
            # Bar chart: max 10 blocks
            bar_len = max(1, round((amount / max_amount) * 10))
            bar = "█" * bar_len + "░" * (10 - bar_len)
            amount_str = fmt(amount, user.default_currency)
            lines.append(f"`{date_str}` {day_name[:3]} {bar} *{amount_str}* {is_today}")
        else:
            lines.append(f"`{date_str}` {day_name[:3]} {'░' * 10} —  {is_today}")

    lines.append(f"\n💸 *Итого за неделю: {fmt(total_week, user.default_currency)}*")

    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message, session: AsyncSession):
    """Show total balance for current month."""
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name
    )

    today = date.today()
    month_start = today.replace(day=1)

    total_income = float(await TransactionRepository.get_total(session, user.id, month_start, today, "income"))
    total_expense = float(await TransactionRepository.get_total(session, user.id, month_start, today, "expense"))
    balance = total_income - total_expense
    balance_emoji = "📈" if balance >= 0 else "📉"

    report = (
        f"💰 *Баланс за {today.strftime('%B %Y')}*\n\n"
        f"📥 Доходы: {fmt(total_income, user.default_currency)}\n"
        f"📤 Расходы: {fmt(total_expense, user.default_currency)}\n"
        f"{balance_emoji} Баланс: {fmt(balance, user.default_currency)}"
    )
    await message.answer(report, parse_mode="Markdown", reply_markup=get_main_keyboard())


@router.message(Command("reset"))
async def cmd_reset(message: Message):
    """Ask for confirmation before deleting all transactions."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Да, удалить всё", callback_data="reset_confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="reset_cancel"),
        ]
    ])
    await message.answer(
        "⚠️ *Удалить все транзакции?*\n\n"
        "Это действие удалит все твои записи о расходах и доходах. "
        "Отменить будет невозможно.\n\n"
        "Уверен?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "reset_confirm")
async def callback_reset_confirm(callback, session: AsyncSession):
    """Delete all transactions for the user after confirmation."""
    user = await UserRepository.get_or_create(
        session, callback.from_user.id,
        callback.from_user.username, callback.from_user.first_name
    )
    await session.execute(
        sql_delete(Transaction).where(Transaction.user_id == user.id)
    )
    await session.execute(sql_delete(CsvImport).where(CsvImport.user_id == user.id))
    await callback.message.edit_text(
        "🗑 *Все транзакции удалены.*\n\nМожешь начинать с чистого листа! 🆕",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data == "reset_cancel")
async def callback_reset_cancel(callback):
    """Cancel the reset operation."""
    await callback.message.edit_text("✅ Отменено. Данные не удалены.")
    await callback.answer()

MONTH_NAMES = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]

@router.message(F.text == "📅 Расходы за месяц")
@router.message(Command("month"))
async def cmd_month_menu(message: Message):
    """Show inline keyboard with months of the current year."""
    today = date.today()
    year = today.year
    
    keyboard = []
    row = []
    
    # Show all 12 months sequentially in a compact 3x4 grid
    for m in range(1, 13):
        month_name = MONTH_NAMES[m-1]
        btn_text = f"{m:02d} | {month_name}"
        btn = InlineKeyboardButton(text=btn_text, callback_data=f"month_report:{year}-{m:02d}")
        row.append(btn)
        
        if len(row) == 3:
            keyboard.append(row)
            row = []
            
    if row:
        keyboard.append(row)

    await message.answer(
        f"📅 *Отчет за {year} год*\nВыберите месяц:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

import calendar

@router.callback_query(F.data.startswith("month_report:"))
async def process_month_report(callback, session: AsyncSession):
    """Show detailed report for the selected month."""
    _, year_month = callback.data.split(":")
    year, month = map(int, year_month.split("-"))

    user = await UserRepository.get_or_create(
        session, callback.from_user.id,
        callback.from_user.username, callback.from_user.first_name
    )

    last_day = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    summary = await TransactionRepository.get_summary_by_category(
        session, user.id, start_date, end_date, "expense"
    )
    
    name_display = f"{MONTH_NAMES[month-1]} {year}"

    if not summary:
        await callback.message.edit_text(
            f"📅 *Расходы за {name_display}*\n\nВ этом месяце расходов нет.",
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    lines = [f"📅 *Расходы за {name_display}*\n"]
    total = 0
    for cat, amount in summary:
        total += float(amount)
        icon = CATEGORY_ICON_MAP.get(cat or "Другое", "❓")
        cat_name = cat or "Другое"
        lines.append(f"{icon} {cat_name} — *{fmt(float(amount), user.default_currency)}*")

    lines.append(f"\n💸 *Итого за месяц: {fmt(total, user.default_currency)}*")

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown"
    )
    await callback.answer()
