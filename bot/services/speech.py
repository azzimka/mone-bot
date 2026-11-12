import asyncio
import logging
from pathlib import Path
import aiofiles
from groq import AsyncGroq
from bot.services.i18n import current_language

logger = logging.getLogger(__name__)


class SpeechService:
    def __init__(self, api_key: str, max_concurrency: int = 20):
        """Initialize the SpeechService with pooled async Groq client."""
        self.client = AsyncGroq(api_key=api_key, timeout=30.0, max_retries=1)
        self.model = "whisper-large-v3-turbo"
        self._semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))

    async def close(self) -> None:
        await self.client.close()

    async def transcribe(self, audio_path: str) -> str:
        """
        Asynchronously transcribes an audio file using Groq Whisper API.
        
        Args:
            audio_path: Path to the audio file (.ogg)
            
        Returns:
            Transcribed text or an error message.
        """
        try:
            async with aiofiles.open(audio_path, "rb") as file:
                audio_bytes = await file.read()
            async with self._semaphore:
                transcription = await self.client.audio.transcriptions.create(
                    file=(Path(audio_path).name, audio_bytes),
                    model=self.model,
                    language=current_language.get(),
                    response_format="text",
                )
            return transcription
        except Exception as e:
            logger.error(f"Transcription failed for {audio_path}: {e}")
            return "К сожалению, не удалось распознать голосовое сообщение. Попробуйте еще раз или напишите текстом."
