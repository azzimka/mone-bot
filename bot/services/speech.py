import asyncio
import logging
from pathlib import Path
from groq import Groq

logger = logging.getLogger(__name__)

class SpeechService:
    def __init__(self, api_key: str):
        """Initialize the SpeechService with Groq client."""
        self.client = Groq(api_key=api_key)
        self.model = "whisper-large-v3-turbo"

    async def transcribe(self, audio_path: str) -> str:
        """
        Asynchronously transcribes an audio file using Groq Whisper API.
        
        Args:
            audio_path: Path to the audio file (.ogg)
            
        Returns:
            Transcribed text or an error message.
        """
        try:
            return await asyncio.to_thread(self._transcribe_sync, audio_path)
        except Exception as e:
            logger.error(f"Transcription failed for {audio_path}: {e}")
            return "К сожалению, не удалось распознать голосовое сообщение. Попробуйте еще раз или напишите текстом."

    def _transcribe_sync(self, audio_path: str) -> str:
        """Synchronous wrapper for Groq transcription."""
        with open(audio_path, "rb") as file:
            transcription = self.client.audio.transcriptions.create(
                file=(Path(audio_path).name, file.read()),
                model=self.model,
                language="ru",
                response_format="text"
            )
        return transcription
