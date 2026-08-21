import uuid
import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.services.ai_parser import AIParser
from bot.services.reports import ReportService
from bot.handlers.callbacks import pending_transactions
from bot.database.repositories import UserRepository
from bot.handlers.commands import get_main_keyboard

logger = logging.getLogger(__name__)
router = Router()

ai_parser = AIParser(api_key=settings.GROQ_API_KEY)
report_service = ReportService()


@router.message(F.text & ~F.text.startswith('/'))
async def handle_text_message(message: Message, session: AsyncSession):
    """Handle incoming text messages and parse them for transactions."""

    # Ensure user exists
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name
    )

    try:
        # Parse text directly with AIParser
        parsed_result = await ai_parser.parse(message.text, settings.DEFAULT_CURRENCY)

        if not parsed_result or not parsed_result.transactions:
            await message.answer("⚠️ Не удалось распознать финансовые операции в вашем сообщении. Попробуйте написать, например: «Кофе 25000» или «Зарплата 5000000».")
            return

        total_txs = len(parsed_result.transactions)

        # Each transaction gets its own clean confirmation card
        for i, tx in enumerate(parsed_result.transactions, start=1):
            tx_id = str(uuid.uuid4())

            pending_transactions[tx_id] = {
                "user_id": user.id,
                "transaction": tx.model_dump(),
                "voice_text": message.text
            }

            builder = InlineKeyboardBuilder()
            builder.button(text="✅ Верно", callback_data=f"confirm:{tx_id}")
            builder.button(text="❌ Отменить", callback_data=f"cancel:{tx_id}")
            builder.adjust(2)

            # If multiple transactions, add index header "1 из 2"
            header = f"*{i} из {total_txs}*\n" if total_txs > 1 else ""
            # Pass empty string — original text is already visible above
            confirmation_msg = header + report_service.format_transaction_confirmation(tx, "")

            await message.answer(
                confirmation_msg,
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )

    except Exception as e:
        logger.error(f"Error processing text message: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке сообщения. Попробуйте ещё раз.")
