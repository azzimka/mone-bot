from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    GROQ_API_KEY: str
    DATABASE_URL: str
    DEFAULT_CURRENCY: str = "UZS"
    POSTGRES_PASSWORD: Optional[str] = None
    WEB_PUBLIC_URL: str = ""

    # Optional ElevenLabs TTS (used ONLY when user explicitly selects voice reply)
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = "nPczCjzI2devNBz1zQrb"
    ELEVENLABS_MODEL_ID: str = "eleven_v4_turbo"
    ELEVENLABS_OUTPUT_FORMAT: str = "opus_48000_64"
    ELEVENLABS_STABILITY: float = 0.40
    ELEVENLABS_SIMILARITY_BOOST: float = 0.78
    ELEVENLABS_MAX_CHARS: int = 1300
    ELEVENLABS_MAX_CONCURRENCY: int = 2
    ADVISOR_LLM_CONCURRENCY: int = 20

    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
