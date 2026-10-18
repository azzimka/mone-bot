from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TransactionInput(BaseModel):
    type: Literal["income", "expense"]
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2, allow_inf_nan=False)
    date: date
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class TelegramWebAppData(BaseModel):
    init_data: str = Field(min_length=1, max_length=4096)

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PreferencesInput(BaseModel):
    language: Literal["uz", "ru"]
    model_config = ConfigDict(extra="forbid")


class CategoryInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    icon: Literal["food", "car", "home", "shirt", "game", "heart", "book", "work", "phone", "gift", "other", "wallet", "trend", "laptop", "transfer", "scale", "sport", "coffee", "plane", "pet", "cart", "baby", "music", "tools"] | None = None
    parent_name: str | None = Field(default=None, min_length=1, max_length=100)
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)



class CategoryUpdate(CategoryInput):
    key: str = Field(min_length=1, max_length=100)
