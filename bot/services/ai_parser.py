import asyncio
import logging
import json
from typing import Literal, Optional
from decimal import Decimal
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from groq import Groq

logger = logging.getLogger(__name__)

class ParsedTransaction(BaseModel):
    type: Literal["income", "expense", "reconcile"]
    amount: Decimal = Field(ge=0, le=Decimal("9999999999999.99"), max_digits=15, decimal_places=2)
    currency: str = "UZS"
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=2000)

    @field_validator("currency")
    @classmethod
    def valid_currency(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 3 or not value.isascii() or not value.isalpha():
            raise ValueError("Currency must be a three-letter code")
        return value

    @model_validator(mode="after")
    def positive_entry_amount(self):
        if self.type != "reconcile" and self.amount <= 0:
            raise ValueError("Income and expense amounts must be positive")
        return self

class ParsedTransactions(BaseModel):
    transactions: list[ParsedTransaction]
    needs_account_selection: bool = False

    @model_validator(mode="after")
    def do_not_guess_account(self):
        if self.needs_account_selection:
            self.transactions = []
        return self

class AIParser:
    def __init__(self, api_key: str):
        """Initialize the AIParser with Groq client."""
        self.client = Groq(api_key=api_key)
        # Using Qwen 3.8 27B model for superior multi-language (Russian & Uzbek) comprehension
        self.model = "qwen/qwen3.8-27b"
        
    async def parse(self, text: str, default_currency: str = 'UZS') -> Optional[ParsedTransactions]:
        """
        Asynchronously parses transaction details from text using LLM.
        """
        try:
            return await asyncio.to_thread(self._parse_sync, text, default_currency)
        except Exception as e:
            logger.error("Financial message parsing failed (%s)", type(e).__name__)
            return None

    def _parse_sync(self, text: str, default_currency: str) -> ParsedTransactions:
        """Synchronous parsing logic."""
        system_prompt = f"""
Вы умный финансовый ассистент. Ваша задача - извлекать финансовые транзакции и операции из сообщений пользователя.

Каждая транзакция должна содержать: 
- type:
    * "expense" — трата, покупка, оплата (еда, такси, кафе и т.д.)
    * "income" — доход (зарплата, приход, вернули долг, подарок)
    * "reconcile" — сверка / установка фактического баланса ОДНОГО счёта по умолчанию. Используется, когда пользователь сообщает СВОЙ ТЕКУЩИЙ ОСТАТОК / БАЛАНС (например: "мой баланс 50 тысяч", "баланс 50к", "сведи баланс на 50 000", "meni balansim 50 ming", "balans 50000"). Никогда не складывай остатки разных карт, наличных, банковских счетов или валют в один amount. Если для сверки указан конкретный счёт/карта либо несколько счетов или валют, бот не может безопасно выбрать счёт: верни {{"needs_account_selection": true, "transactions": []}}. Не угадывай и не конвертируй валюты.
- amount: число (сумма). Обязательно число без пробелов.
- currency: валюта. Если не указана, используй '{default_currency}'
- category: выбери наиболее подходящую категорию. Для сверки баланса укажи "Сверка". Для остальных: [Еда, Транспорт, Жильё, Одежда, Развлечения, Здоровье, Образование, Работа, Связь, Подарки, Зарплата, Инвестиции, Фриланс, Переводы, Другое]
- description: краткое описание из текста (например "сверка баланса", "кофе", "такси")

Если в тексте вообще нет финансовых операций или чисел — верни пустой список transactions: {{"transactions": []}}.

Верни результат СТРОГО в формате JSON:
{{
  "needs_account_selection": false,
  "transactions": [
    {{
      "type": "expense",
      "amount": 25000,
      "currency": "UZS",
      "category": "Еда",
      "description": "кофе"
    }}
  ]
}}
"""
        logger.debug("Parsing financial message")
        response = self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            model=self.model,
            response_format={"type": "json_object"},
            temperature=0.0
        )
        
        content = response.choices[0].message.content
        
        if not content:
            raise ValueError("Empty response from LLM")
            
        try:
            parsed_json = json.loads(content, parse_float=Decimal)
            if isinstance(parsed_json, dict) and isinstance(parsed_json.get("transactions"), list):
                for item in parsed_json["transactions"]:
                    if isinstance(item, dict) and not item.get("currency"):
                        item["currency"] = default_currency
            result = ParsedTransactions.model_validate(parsed_json)
            logger.debug("Parsed %d financial entries", len(result.transactions))
            return result
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error("Financial response validation failed (%s)", type(e).__name__)
            raise
