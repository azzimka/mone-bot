import asyncio
import logging
import json
from typing import Literal, Optional
from decimal import Decimal
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from groq import Groq

logger = logging.getLogger(__name__)

class ParsedTransaction(BaseModel):
    type: Literal["expense"] = "expense"
    amount: Decimal = Field(gt=0, le=Decimal("9999999999999.99"), max_digits=15, decimal_places=2)
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


class ParsedTransactions(BaseModel):
    transactions: list[ParsedTransaction]

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
Вы умный помощник по учёту расходов. Ваша задача — извлекать ТОЛЬКО расходы (траты, покупки, оплаты) из сообщений пользователя.

ВАЖНО:
- Бот ведёт только учёт расходов.
- НЕ извлекай доходы (зарплата, приход, пополнение, вернули долг, подарок мне) и НЕ извлекай сообщения о балансе/остатке/сверке баланса (например «мой баланс 50 тысяч», «осталось 100к», «зарплата 5 млн»). Для таких сообщений верни пустой список: {{"transactions": []}}.

Каждый расход должен содержать:
- type: всегда "expense"
- amount: положительное число (сумма без пробелов).
- currency: трёхбуквенный код валюты. Если не указана, используй '{default_currency}'. Не конвертируй валюты.
- category: выбери наиболее подходящую категорию из списка: [Еда, Транспорт, Жильё, Одежда, Развлечения, Здоровье, Образование, Работа, Связь, Подарки, Переводы, Другое]
- description: краткое описание расхода из текста (например "кофе", "такси")

Если в тексте нет расходов или чисел — верни пустой список transactions: {{"transactions": []}}.

Верни результат СТРОГО в формате JSON:
{{
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
