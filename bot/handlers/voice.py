import os
import uuid
import logging
import tempfile
from aiogram import Router, F, Bot
from aiogram.types import Message, ContentType
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.services.speech import SpeechService
from bot.services.ai_parser import AIParser
from bot.services.reports import ReportService
from bot.handlers.callbacks import pending_transactions
from bot.database.repositories import UserRepository
from bot.handlers.commands import get_main_keyboard

logger = logging.getLogger(__name__)
router = Router()

speech_service = SpeechService(api_key=settings.GROQ_API_KEY)
ai_parser = AIParser(api_key=settings.GROQ_API_KEY)
report_service = ReportService()


@router.message(F.content_type == ContentType.VOICE)
async def handle_voice_message(message: Message, bot: Bot, session: AsyncSession):
    """Handle incoming voice messages: transcribe, parse, and confirm."""
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    # Ensure user exists
    user = await UserRepository.get_or_create(
        session, message.from_user.id,
        message.from_user.username, message.from_user.first_name
    )

    try:
        # 1. Download voice file
        voice = message.voice
        file_info = await bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_file:
            temp_path = temp_file.name

        await bot.download_file(file_info.file_path, temp_path)

        # 2. Transcribe using SpeechService
        try:
            transcribed_text = await speech_service.transcribe(temp_path)
            if not transcribed_text or transcribed_text.startswith("К сожалению"):
                await message.reply("⚠️ Не удалось распознать голосовое сообщение. Попробуйте ещё раз или напишите текстом.")
                return
        finally:
            # Clean up the temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # Show transcribed text ONCE as a clean header
        await message.reply(f'🎤 *Распознано:* _{transcribed_text}_', parse_mode="Markdown")

        # 3. Parse with AIParser
        parsed_result = await ai_parser.parse(transcribed_text, settings.DEFAULT_CURRENCY)

        if not parsed_result or not parsed_result.transactions:
            await message.answer("⚠️ Не удалось распознать финансовые операции в тексте. Попробуйте сказать точнее, например: «Кофе 25 тысяч».")
            return

        total_txs = len(parsed_result.transactions)

        # 4. Each transaction gets its own clean confirmation card (NO repeated voice text)
        for i, tx in enumerate(parsed_result.transactions, start=1):
            tx_id = str(uuid.uuid4())

            # Store in pending dict
            pending_transactions[tx_id] = {
                "user_id": user.id,
                "transaction": tx.model_dump(),
                "voice_text": transcribed_text
            }

            # Create inline keyboard
            builder = InlineKeyboardBuilder()
            btn_text = "⚖️ Приравнять" if tx.type == "reconcile" else "✅ Верно"
            builder.button(text=btn_text, callback_data=f"confirm:{tx_id}")
            builder.button(text="❌ Отменить", callback_data=f"cancel:{tx_id}")
            builder.adjust(2)

            # If multiple transactions, add index header "1 из 2"
            header = f"*{i} из {total_txs}*\n" if total_txs > 1 else ""
            # Pass empty string so voice text is NOT repeated in each card
            confirmation_msg = header + report_service.format_transaction_confirmation(tx, "")

            await message.answer(
                confirmation_msg,
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )

    except Exception as e:
        logger.error(f"Error processing voice message: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при обработке голосового сообщения. Попробуйте ещё раз.")
