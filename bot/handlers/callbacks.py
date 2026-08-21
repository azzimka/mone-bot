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
