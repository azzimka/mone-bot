from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class AccountInput(Input):
    name: str = Field(min_length=1,max_length=100)
    kind: Literal['cash','card','bank']
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    opening_balance: Decimal = Field(default=Decimal(0),max_digits=15,decimal_places=2,allow_inf_nan=False)

class TransferInput(Input):
    source_id: int = Field(gt=0)
    destination_id: int = Field(gt=0)
    source_amount: Decimal = Field(gt=0,max_digits=15,decimal_places=2,allow_inf_nan=False)
    destination_amount: Decimal | None = Field(default=None,gt=0,max_digits=15,decimal_places=2,allow_inf_nan=False)
    date: date
    description: str = Field(default='',max_length=2000)
    request_key: str = Field(min_length=16,max_length=64,pattern=r'^[a-zA-Z0-9-]+$')

class BudgetInput(Input):
    month: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    category: str = Field(default='',max_length=100)
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    amount: Decimal = Field(gt=0,max_digits=15,decimal_places=2,allow_inf_nan=False)
    notify_telegram: bool = False

    @field_validator('month')
    @classmethod
    def valid_month(cls,value):
        if not '2000-01' <= value <= '2100-12': raise ValueError('Month out of range')
        return value

class RecurringInput(Input):
    account_id: int = Field(gt=0)
    type: Literal['income','expense']
    amount: Decimal = Field(gt=0,max_digits=15,decimal_places=2,allow_inf_nan=False)
    category: str = Field(min_length=1,max_length=100)
    description: str = Field(default='',max_length=2000)
    frequency: Literal['daily','weekly','monthly']
    next_date: date

class EnabledInput(Input):
    enabled: bool

class ArchiveInput(Input):
    key: str = Field(min_length=1,max_length=100)
    archived: bool

class CsvInspectInput(Input):
    content: str = Field(min_length=1,max_length=1048576)
    filename: str = Field(default='import.csv',max_length=255)

class CsvPreviewInput(CsvInspectInput):
    mapping: dict[str,str] = Field(max_length=8)
    account_id: int = Field(gt=0)
    skip_duplicates: bool = True
