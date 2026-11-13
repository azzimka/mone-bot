import logging
from datetime import date, timedelta
from decimal import Decimal
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeChat, MenuButtonDefault, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.database.repositories import UserRepository, CategoryRepository, TransactionRepository
from bot.models.transaction import Transaction
from bot.models.csv_import import CsvImport
from bot.services.finance import local_today
from bot.services.i18n import current_language, tr, button_variants

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
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=tr("💰 Баланс")), KeyboardButton(text=tr("📋 Расходы за сегодня"))],
            [KeyboardButton(text=tr("📅 История расходов"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# A client may still display a reply keyboard sent before the update.
@router.message(F.text.in_({
    "🧠 AI-финансист", "🧠 AI-moliyachi",
    "📊 Разбор за месяц", "📊 Oylik tahlil",
    "🔍 На что я часто трачу?", "🔍 Ko‘p sarflanadigan joylar",
    "💡 Проверить покупку", "💡 Xaridni tekshirish",
    "🗑 Новый диалог", "🗑 Yangi suhbat",
    "⬅️ Выйти из режима", "⬅️ Rejimdan chiqish",
}))
async def refresh_old_keyboard(message: Message):
    await message.answer(tr("Меню обновлено."), reply_markup=get_main_keyboard())


def fmt(amount: Decimal | float | int, currency: str = "UZS") -> str:
    """Format ledger values without losing cents or converting to float."""
    value = Decimal(str(amount))
    number = f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    return f"{number} {currency}"


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext):
    """Handle /start command, register user and seed defaults."""
    await state.clear()
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
            BotCommand(command="start", description="Boshlash" if uz else "Начать"),
        ], scope=BotCommandScopeChat(chat_id=telegram_id))
        await bot.set_chat_menu_button(chat_id=telegram_id, menu_button=MenuButtonDefault())
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
        await message.answer(tr("Сайт пока не настроен."))
        return
    await message.answer("⚙️ Sozlamalar" if current_language.get() == "uz" else "⚙️ Настройки", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚙️ Sozlamalarni ochish" if current_language.get() == "uz" else "⚙️ Открыть настройки", url=web_settings_url())]]))


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    await send_settings_link(message)


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        tr("🎤 Напишите сообщение или отправьте голосовое.\n"
           "✅ Проверьте и подтвердите операцию.\n"
           "📅 История расходов — отчёт за день или месяц.\n"
           "📥 Для CSV — /import."),
        reply_markup=get_main_keyboard(),
    )


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
    total_week = await TransactionRepository.get_total(
        session, user.id, week_ago, today, "expense"
    )
    kb = get_main_keyboard()

    if not daily_totals:
        await message.answer(
            tr('📊 *Расходы за неделю*\n\nЗа последние 7 дней расходов нет.'),
            parse_mode="Markdown",
            reply_markup=kb,
        )
        return

    # Build a dict of all days in range
    daily_dict: dict[date, Decimal] = {}
    for d in range((today-week_ago).days+1):
        day = week_ago + timedelta(days=d)
        daily_dict[day] = Decimal(0)
    for tx_date, amount in daily_totals:
        daily_dict[tx_date] = amount

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
        reply_markup=kb,
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message, session: AsyncSession):
    """Use the same current-balance screen for the command and menu button."""
    from bot.handlers.balance import cmd_balance as show_balance
    await show_balance(message, session)


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
