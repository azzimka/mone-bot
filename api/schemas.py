from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransactionInput(BaseModel):
    type: Literal["income", "expense"]
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2, allow_inf_nan=False)
    date: date
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    account_id: int | None = Field(default=None, gt=0)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TelegramWebAppData(BaseModel):
    init_data: str = Field(min_length=1, max_length=4096)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PreferencesInput(BaseModel):
    language: Literal["uz", "ru"] | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    week_start: int | None = Field(default=None, ge=0, le=6)
    quick_categories: list[str] | None = Field(default=None, max_length=6)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        if value:
            try: ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError): raise ValueError("Unknown time zone")
        return value

    model_config = ConfigDict(extra="forbid")


class CategoryInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    icon: str | None = Field(default=None,max_length=10)
    name_uz: str | None = Field(default=None,min_length=1,max_length=100)
    name_ru: str | None = Field(default=None,min_length=1,max_length=100)

    @field_validator("icon")
    @classmethod
    def valid_icon(cls,value):
        from bot.services.categories import ICON_KEYS
        if value is not None and value not in ICON_KEYS:raise ValueError("Unknown category icon")
        return value

    parent_name: str | None = Field(default=None, min_length=1, max_length=100)
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)



class CategoryUpdate(CategoryInput):
    key: str = Field(min_length=1, max_length=100)
