import logging
from datetime import date, datetime, timedelta
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.repositories import TransactionRepository
from bot.services.reports import ReportService

logger = logging.getLogger(__name__)
router = Router()
report_service = ReportService()

# In-memory dict for pending transactions
# Format: UUID -> {"user_id": int, "transaction": dict, "voice_text": str}
pending_transactions: dict[str, dict] = {}


@router.callback_query(F.data.startswith("confirm:"))
async def on_confirm_transaction(callback: CallbackQuery, session: AsyncSession):
    """Handle transaction confirmation — save to database."""
    tx_id = callback.data.split(":", 1)[1]

    pending_data = pending_transactions.get(tx_id)
    if not pending_data:
        await callback.message.edit_text("❌ Данная операция уже обработана или устарела.")
        await callback.answer()
        return

    # Extract data
    user_id = pending_data["user_id"]
    tx_dict = pending_data["transaction"]
    voice_text = pending_data.get("voice_text", "")

    # Special handling for balance reconciliation
    if tx_dict["type"] == "reconcile":
        from decimal import Decimal
        from sqlalchemy import select, func
        from bot.models.transaction import Transaction as TxModel

        target_amount = Decimal(str(tx_dict["amount"]))
        currency = tx_dict.get("currency", "UZS")

        stmt_income = select(func.coalesce(func.sum(TxModel.amount), 0)).where(
            TxModel.user_id == user_id, TxModel.type == "income"
        )
        stmt_expense = select(func.coalesce(func.sum(TxModel.amount), 0)).where(
            TxModel.user_id == user_id, TxModel.type == "expense"
        )
        income_total = (await session.execute(stmt_income)).scalar() or Decimal("0")
        expense_total = (await session.execute(stmt_expense)).scalar() or Decimal("0")
        current_balance = Decimal(str(income_total)) - Decimal(str(expense_total))

        diff = target_amount - current_balance

        if diff > 0:
            diff_fmt = f"{float(diff):,.0f}".replace(",", " ")
            await TransactionRepository.create(
                session=session,
                user_id=user_id,
                type="income",
                amount=diff,
                currency=currency,
                category="Сверка",
                description=f"Сверка (+{diff_fmt} {currency})",
                voice_text=voice_text,
                date=date.today(),
            )
            diff_str = f"+{diff_fmt} {currency} (доход)"
        elif diff < 0:
            abs_diff = abs(diff)
            abs_diff_fmt = f"{float(abs_diff):,.0f}".replace(",", " ")
            await TransactionRepository.create(
                session=session,
                user_id=user_id,
                type="expense",
                amount=abs_diff,
                currency=currency,
                category="Сверка",
                description=f"Сверка (-{abs_diff_fmt} {currency})",
                voice_text=voice_text,
                date=date.today(),
            )
            diff_str = f"-{abs_diff_fmt} {currency} (расход)"
        else:
            diff_str = "0 UZS (совпадает)"

        curr_fmt = f"{float(current_balance):,.0f}".replace(",", " ")
        target_fmt = f"{float(target_amount):,.0f}".replace(",", " ")

        success_text = (
            f"⚖️ *Баланс синхронизирован!*\n\n"
            f"├ Было в боте:  `{curr_fmt} {currency}`\n"
            f"├ Корректировка: `{diff_str}`\n"
            f"└ Фактический:   *{target_fmt} {currency}* 🟢"
        )
        await callback.message.edit_text(success_text, parse_mode="Markdown")
        del pending_transactions[tx_id]
        await callback.answer("⚖️ Баланс сверен!")
        return

    # Save to database
    await TransactionRepository.create(
        session=session,
        user_id=user_id,
        type=tx_dict["type"],
        amount=tx_dict["amount"],
        currency=tx_dict.get("currency", "UZS"),
        category=tx_dict.get("category", "Другое"),
        description=tx_dict.get("description", ""),
        voice_text=voice_text,
        date=date.today(),
    )

    # Format success message
    type_emoji = "📥" if tx_dict["type"] == "income" else "📤"
    type_str = "Доход" if tx_dict["type"] == "income" else "Расход"
    amount = tx_dict["amount"]
    currency = tx_dict.get("currency", "UZS")
    amount_str = f"{amount:,.0f}".replace(",", " ")

    success_text = (
        f"✅ *Записано!*\n"
        f"{type_emoji} Тип: {type_str}\n"
        f"💰 Сумма: {amount_str} {currency}\n"
        f"📂 Категория: {tx_dict.get('category', 'Другое')}\n"
        f"📝 Описание: {tx_dict.get('description', '-')}"
    )

    # For expenses: show remaining balance
    if tx_dict["type"] == "expense":
        from sqlalchemy import select, func
        from bot.models.transaction import Transaction as TxModel

        stmt_income = select(func.coalesce(func.sum(TxModel.amount), 0)).where(
            TxModel.user_id == user_id, TxModel.type == "income"
        )
        stmt_expense = select(func.coalesce(func.sum(TxModel.amount), 0)).where(
            TxModel.user_id == user_id, TxModel.type == "expense"
        )
        income_total = (await session.execute(stmt_income)).scalar() or 0
        expense_total = (await session.execute(stmt_expense)).scalar() or 0
        balance = float(income_total) - float(expense_total)

        # Only show balance if user has set it up (income > 0)
        if float(income_total) > 0:
            balance_str = f"{balance:,.0f}".replace(",", " ")
            success_text += f"\n\n💵 Остаток: *{balance_str} {currency}*"

    await callback.message.edit_text(success_text, parse_mode="Markdown")

    # Clean up
    del pending_transactions[tx_id]
    await callback.answer("✅ Успешно сохранено!")


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel_transaction(callback: CallbackQuery):
    """Handle transaction cancellation."""
    tx_id = callback.data.split(":", 1)[1]

    if tx_id in pending_transactions:
        del pending_transactions[tx_id]

    await callback.message.edit_text("❌ Операция отменена.")
    await callback.answer("Отменено")
