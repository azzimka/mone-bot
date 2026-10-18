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
    
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
