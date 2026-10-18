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
