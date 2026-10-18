from bot.services.i18n import category_label, tr, button_variants
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
        await callback.message.edit_text(tr('❌ Данная операция уже обработана или устарела.'))
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
            diff_str = tr('+{p1} {p3} (доход)' ,p1=f'{diff_fmt}', p3=f'{currency}')
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
            diff_str = tr('-{p1} {p3} (расход)' ,p1=f'{abs_diff_fmt}', p3=f'{currency}')
        else:
            diff_str = tr('0 UZS (совпадает)')

        curr_fmt = f"{float(current_balance):,.0f}".replace(",", " ")
        target_fmt = f"{float(target_amount):,.0f}".replace(",", " ")

        success_text = (
            tr('⚖️ *Баланс синхронизирован!*\n\n├ Было в боте:  `{p1} {p3}`\n├ Корректировка: `{p5}`\n└ Фактический:   *{p7} {p9}* 🟢' ,p1=f'{curr_fmt}', p3=f'{currency}', p5=f'{diff_str}', p7=f'{target_fmt}', p9=f'{currency}')
        )
        await callback.message.edit_text(success_text, parse_mode="Markdown")
        del pending_transactions[tx_id]
        await callback.answer(tr('⚖️ Баланс сверен!'))
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
    type_str = tr('Доход') if tx_dict["type"] == "income" else tr('Расход')
    amount = tx_dict["amount"]
    currency = tx_dict.get("currency", "UZS")
    amount_str = f"{amount:,.0f}".replace(",", " ")

    success_text = f"✅ {type_str}: {amount_str} {currency}\n📂 {category_label(tx_dict.get('category', 'Другое'))}"

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
            success_text += tr('\n\n💵 Остаток: *{p1} {p3}*' ,p1=f'{balance_str}', p3=f'{currency}')

    await callback.message.edit_text(success_text, parse_mode="Markdown")

    # Clean up
    del pending_transactions[tx_id]
    await callback.answer(tr('✅ Успешно сохранено!'))


@router.callback_query(F.data.startswith("cancel:"))
async def on_cancel_transaction(callback: CallbackQuery):
    """Handle transaction cancellation."""
    tx_id = callback.data.split(":", 1)[1]

    if tx_id in pending_transactions:
        del pending_transactions[tx_id]

    await callback.message.edit_text(tr('❌ Операция отменена.'))
    await callback.answer(tr('Отменено'))
