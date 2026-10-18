from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebSettings(BaseSettings):
    DATABASE_URL: str
    TELEGRAM_BOT_USERNAME: str = ""
    WEB_PUBLIC_URL: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("WEB_PUBLIC_URL")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("WEB_PUBLIC_URL must be an http(s) origin without a path")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Public deployments require HTTPS")
        return value.rstrip("/")
