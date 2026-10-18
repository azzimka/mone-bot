import logging
from datetime import date, timedelta
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeChat, MenuButtonWebApp, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.repositories import UserRepository, CategoryRepository, TransactionRepository, CATEGORY_ICON_MAP
from bot.models.transaction import Transaction
from bot.models.csv_import import CsvImport
from bot.services.finance import local_today
from bot.services.i18n import category_label, current_language, tr, button_variants

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
            KeyboardButton(text=tr('📱 Открыть приложение'), web_app=WebAppInfo(url=settings.WEB_PUBLIC_URL)),
        ])
    rows.append([KeyboardButton(text=tr("💰 Баланс")), KeyboardButton(text=tr("📋 Расходы за сегодня"))])
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

    await send_welcome(message, user.first_name, message.bot, user.telegram_id)


async def configure_chat_menu(bot, telegram_id: int) -> bool:
    try:
        uz = current_language.get() == "uz"
        await bot.set_my_commands([
            BotCommand(command="app", description="📱 Ilova" if uz else "📱 Приложение"),
            BotCommand(command="today", description="📋 Bugun" if uz else "📋 Сегодня"),
            BotCommand(command="import", description="📥 CSV import" if uz else "📥 Импорт CSV"),
            BotCommand(command="settings", description="⚙️ Sozlamalar" if uz else "⚙️ Настройки"),
            BotCommand(command="help", description="❓ Yordam" if uz else "❓ Помощь"),
        ], scope=BotCommandScopeChat(chat_id=telegram_id))
        if settings.WEB_PUBLIC_URL:
            await bot.set_chat_menu_button(chat_id=telegram_id, menu_button=MenuButtonWebApp(text="📱 Kabinet" if current_language.get() == "uz" else "📱 Кабинет", web_app=WebAppInfo(url=settings.WEB_PUBLIC_URL)))
        return True
    except Exception:
        logger.warning("Could not update per-chat language menu")
        return False


async def send_welcome(message: Message, first_name: str | None, bot=None, telegram_id: int | None = None):
    if bot is not None and telegram_id is not None:
        await configure_chat_menu(bot, telegram_id)
    greeting = f"👋 Salom, {first_name or 'Mone'}!\n\n🎤 Kirim yoki chiqimni yozing yoki ayting.\nMasalan: Qahva 25000." if current_language.get() == "uz" else f"👋 Привет, {first_name or 'Mone'}!\n\n🎤 Напишите или скажите доход или расход.\nНапример: Кофе 25000."
    await message.answer(greeting, reply_markup=get_main_keyboard())


def web_settings_url() -> str:
    return settings.WEB_PUBLIC_URL.rstrip("/") + "/?view=settings"


async def send_settings_link(message: Message):
    if not settings.WEB_PUBLIC_URL:
        await message.answer(tr("Веб-приложение пока не настроено."))
        return
    await message.answer("⚙️ Sozlamalar" if current_language.get() == "uz" else "⚙️ Настройки", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚙️ Sozlamalarni ochish" if current_language.get() == "uz" else "⚙️ Открыть настройки", web_app=WebAppInfo(url=web_settings_url()))]]))


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    await send_settings_link(message)


@router.message(Command("app"))
async def cmd_app(message: Message):
    """Open WebApp Mini App."""
    if not settings.WEB_PUBLIC_URL:
        await message.answer(tr('Веб-приложение пока не настроено.'))
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text=tr('🚀 Открыть Mone Mini App'), web_app=WebAppInfo(url=settings.WEB_PUBLIC_URL)),
        ]]
    )
    await message.answer(tr('Нажми кнопку ниже, чтобы открыть финансовый кабинет прямо в Telegram:'), reply_markup=kb)


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Detailed help message."""
    text = "🎤 Xabar yozing yoki ovoz yuboring.\n✅ Tekshirib tasdiqlang.\n📱 Ilovada hisobotlar va sozlamalar.\n📥 CSV uchun /import." if current_language.get() == "uz" else "🎤 Напишите сообщение или отправьте голосовое.\n✅ Проверьте и подтвердите.\n📱 Отчёты и настройки — в приложении.\n📥 Для CSV — /import."
    await message.answer(text, reply_markup=get_main_keyboard())



@router.message(F.text.in_(button_variants('🚌 Автобус / Метро — 2 000 сум')))
async def cmd_quick_transport(message: Message, session: AsyncSession):
    """Instantly record a fixed 2000 UZS public transport expense."""
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name
    )

    if user.default_currency != "UZS":
        await message.answer("Bu tezkor tugma faqat UZS uchun. / Эта быстрая кнопка доступна только для UZS.")
        return

    await TransactionRepository.create(
        session=session,
        user_id=user.id,
        type="expense",
        amount=2000,
        currency=user.default_currency,
        category="Транспорт",
        description="Автобус / Метро",
        voice_text=None,
        date=local_today(user),
    )

    # Count how many times used today
    today_txs = await TransactionRepository.get_by_period(
        session, user.id, local_today(user), local_today(user), tx_type="expense"
    )
    transport_today = sum(
        1 for t in today_txs
        if t.description == "Автобус / Метро"
    )

    await message.answer(
        tr('🚌 *2 000 {p1}* — записано!\n_Транспорт сегодня: {p3} раз · {p5}_' ,p1=f'{user.default_currency}', p3=f'{transport_today}', p5=f'{fmt(transport_today * 2000, user.default_currency)}'),
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


@router.message(F.text.in_(button_variants('📋 Расходы за сегодня')))
@router.message(Command("today"))
async def cmd_today(message: Message, session: AsyncSession):
    """Detailed today's expense report — every transaction + total."""
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name
    )

    today = local_today(user)
    transactions = await TransactionRepository.get_by_period(
        session, user.id, today, today, tx_type="expense"
    )
    total = float(await TransactionRepository.get_total(
        session, user.id, today, today, "expense"
    ))

    if not transactions:
        await message.answer(
            tr('📋 *{p1} — расходов нет*\n\nСкажи мне голосом или напиши, на что потратил деньги 🎤' ,p1=f"{today.strftime('%d.%m.%Y')}"),
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(),
        )
        return

    from datetime import timezone, timedelta
    uzb_tz = timezone(timedelta(hours=5))
    
    lines = [tr('📋 *Расходы за {p1}*\n' ,p1=f"{today.strftime('%d.%m.%Y')}")]
    for tx in transactions:
        icon = CATEGORY_ICON_MAP.get(tx.category or "Другое", "❓")
        amount_str = fmt(float(tx.amount), tx.currency)
        desc = tx.description or tx.category or "—"
        
        # Format time to UTC+5 (Uzbekistan)
        time_str = tx.created_at.astimezone(uzb_tz).strftime("%H:%M")
        
        lines.append(f"`{time_str}` {icon} {desc} — *{amount_str}*")

    lines.append(tr('\n💸 *Итого: {p1}*' ,p1=f'{fmt(total, user.default_currency)}'))

    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(),
    )


@router.message(F.text.in_(button_variants('📊 Расходы за неделю')))
@router.message(Command("week"))
async def cmd_week(message: Message, session: AsyncSession):
    """Weekly expense report — daily breakdown for last 7 days."""
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name
    )

    today = local_today(user)
    week_ago = today - timedelta(days=(today.weekday()-(user.week_start or 0))%7)

    # Get daily totals
    daily_totals = await TransactionRepository.get_daily_totals(
        session, user.id, week_ago, today, tx_type="expense"
    )
    total_week = float(await TransactionRepository.get_total(
        session, user.id, week_ago, today, "expense"
    ))

    if not daily_totals:
        await message.answer(
            tr('📊 *Расходы за неделю*\n\nЗа последние 7 дней расходов нет.'),
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(),
        )
        return

    # Build a dict of all days in range
    daily_dict: dict[date, float] = {}
    for d in range((today-week_ago).days+1):
        day = week_ago + timedelta(days=d)
        daily_dict[day] = 0.0
    for tx_date, amount in daily_totals:
        daily_dict[tx_date] = float(amount)

    # Find max for bar scaling
    max_amount = max(daily_dict.values()) if daily_dict.values() else 1

    lines = [tr('📊 *Расходы за последние 7 дней*\n')]
    for day, amount in sorted(daily_dict.items()):
        day_name = tr(WEEKDAY_NAMES[day.weekday()])
        date_str = day.strftime("%d.%m")
        is_today = tr('← сегодня') if day == today else ""

        if amount > 0:
            # Bar chart: max 10 blocks
            bar_len = max(1, round((amount / max_amount) * 10))
            bar = "█" * bar_len + "░" * (10 - bar_len)
            amount_str = fmt(amount, user.default_currency)
            lines.append(f"`{date_str}` {day_name[:3]} {bar} *{amount_str}* {is_today}")
        else:
            lines.append(f"`{date_str}` {day_name[:3]} {'░' * 10} —  {is_today}")

    lines.append(tr('\n💸 *Итого за неделю: {p1}*' ,p1=f'{fmt(total_week, user.default_currency)}'))

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

    today = local_today(user)
    month_start = today.replace(day=1)

    total_income = float(await TransactionRepository.get_total(session, user.id, month_start, today, "income"))
    total_expense = float(await TransactionRepository.get_total(session, user.id, month_start, today, "expense"))
    balance = total_income - total_expense
    balance_emoji = "📈" if balance >= 0 else "📉"

    report = (
        tr('💰 *Баланс за {p1}*\n\n📥 Доходы: {p3}\n📤 Расходы: {p5}\n{p7} Баланс: {p9}' ,p1=f"{today.strftime('%B %Y')}", p3=f'{fmt(total_income, user.default_currency)}', p5=f'{fmt(total_expense, user.default_currency)}', p7=f'{balance_emoji}', p9=f'{fmt(balance, user.default_currency)}')
    )
    await message.answer(report, parse_mode="Markdown", reply_markup=get_main_keyboard())


@router.message(Command("reset"))
async def cmd_reset(message: Message):
    """Ask for confirmation before deleting all transactions."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=tr('🗑 Да, удалить всё'), callback_data="reset_confirm"),
            InlineKeyboardButton(text=tr('❌ Отмена'), callback_data="reset_cancel"),
        ]
    ])
    await message.answer(
        tr('⚠️ *Удалить все транзакции?*\n\nЭто действие удалит все твои записи о расходах и доходах. Отменить будет невозможно.\n\nУверен?'),
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
        tr('🗑 *Все транзакции удалены.*\n\nМожешь начинать с чистого листа! 🆕'),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data == "reset_cancel")
async def callback_reset_cancel(callback):
    """Cancel the reset operation."""
    await callback.message.edit_text(tr('✅ Отменено. Данные не удалены.'))
    await callback.answer()

MONTH_NAMES = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]

@router.message(F.text.in_(button_variants('📅 Расходы за месяц')))
@router.message(Command("month"))
async def cmd_month_menu(message: Message):
    """Show inline keyboard with months of the current year."""
    today = date.today()
    year = today.year
    
    keyboard = []
    row = []
    
    # Show all 12 months sequentially in a compact 3x4 grid
    for m in range(1, 13):
        month_name = tr(MONTH_NAMES[m-1])
        btn_text = f"{m:02d} | {month_name}"
        btn = InlineKeyboardButton(text=btn_text, callback_data=f"month_report:{year}-{m:02d}")
        row.append(btn)
        
        if len(row) == 3:
            keyboard.append(row)
            row = []
            
    if row:
        keyboard.append(row)

    await message.answer(
        tr('📅 *Отчет за {p1} год*\nВыберите месяц:' ,p1=f'{year}'),
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
    
    name_display = f"{tr(MONTH_NAMES[month-1])} {year}"

    if not summary:
        await callback.message.edit_text(
            tr('📅 *Расходы за {p1}*\n\nВ этом месяце расходов нет.' ,p1=f'{name_display}'),
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    lines = [tr('📅 *Расходы за {p1}*\n' ,p1=f'{name_display}')]
    total = 0
    for cat, amount in summary:
        total += float(amount)
        icon = CATEGORY_ICON_MAP.get(cat or "Другое", "❓")
        cat_name = category_label(cat or "Другое")
        lines.append(f"{icon} {cat_name} — *{fmt(float(amount), user.default_currency)}*")

    lines.append(tr('\n💸 *Итого за месяц: {p1}*' ,p1=f'{fmt(total, user.default_currency)}'))

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="Markdown"
    )
    await callback.answer()
