from bot.services.i18n import tr, current_language
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
from bot.services.finance import owned_account

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
        parsed_result = await ai_parser.parse(message.text, user.default_currency)

        if parsed_result and parsed_result.needs_account_selection:
            await message.answer("💳 Hisoblarni alohida tekshiring. Bir nechta hisob yoki valyuta qoldig‘ini qo‘shib tenglashtirib bo‘lmaydi. Hisoblar ilovada ko‘rinadi." if current_language.get() == "uz" else "💳 Проверьте счета отдельно. Нельзя сверять суммой остатки разных счетов или валют. Счета доступны в приложении.", reply_markup=get_main_keyboard())
            return

        if not parsed_result or not parsed_result.transactions:
            await message.answer(tr('⚠️ Не удалось распознать финансовые операции в вашем сообщении. Попробуйте написать, например: «Кофе 25000» или «Зарплата 5000000».'))
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
            account = None
            if tx.type == "reconcile":
                account = await owned_account(session, user, None, tx.currency)
                pending_transactions[tx_id]["transaction"]["account_id"] = account.id

            builder = InlineKeyboardBuilder()
            btn_text = tr('⚖️ Приравнять') if tx.type == "reconcile" else tr('✅ Верно')
            builder.button(text=btn_text, callback_data=f"confirm:{tx_id}")
            builder.button(text=tr('❌ Отменить'), callback_data=f"cancel:{tx_id}")
            builder.adjust(2)

            # If multiple transactions, add index header "1 из 2"
            header = tr('*{p1} из {p3}*\n' ,p1=f'{i}', p3=f'{total_txs}') if total_txs > 1 else ""
            # Pass empty string — original text is already visible above
            confirmation_msg = header + report_service.format_transaction_confirmation(tx, "")
            if account is not None:
                # Keep scope visible before approval. Other accounts stay separate.
                account_name = account.name.replace("_", "\\_").replace("*", "\\*").replace("[", "\\[").replace("`", "\\`")
                confirmation_msg += (f"\n\n💳 Faqat hisob: {account_name}" if current_language.get() == "uz" else f"\n\n💳 Только счёт: {account_name}")

            await message.answer(
                confirmation_msg,
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )

    except Exception as e:
        logger.error(f"Error processing text message: {e}", exc_info=True)
        await message.answer(tr('❌ Произошла ошибка при обработке сообщения. Попробуйте ещё раз.'))
