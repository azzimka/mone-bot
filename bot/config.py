from pydantic_settings import BaseSettings
from pydantic import ConfigDict

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    GROQ_API_KEY: str
    DATABASE_URL: str
    DEFAULT_CURRENCY: str = "UZS"
    
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
