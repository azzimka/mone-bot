import asyncio
import logging
import json
from typing import Literal, Optional
from pydantic import BaseModel, ValidationError
from groq import Groq

logger = logging.getLogger(__name__)

class ParsedTransaction(BaseModel):
    type: Literal["income", "expense"]
    amount: float
    currency: str = "UZS"
    category: str
    description: str

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
            logger.error(f"Failed to parse text: {e}")
            return None

    def _parse_sync(self, text: str, default_currency: str) -> ParsedTransactions:
        """Synchronous parsing logic."""
        system_prompt = f"""
Вы умный финансовый ассистент. Ваша задача - извлекать финансовые транзакции из сообщений пользователя.

Каждая транзакция должна содержать: 
- type: "income" (если это доход, зарплата, пополнение, баланс) ИЛИ "expense" (если это трата, покупка)
- amount: число (сумма)
- currency: валюта. Если не указана, используй '{default_currency}'
- category: выбери одну наиболее подходящую из списка: [Еда, Транспорт, Жильё, Одежда, Развлечения, Здоровье, Образование, Работа, Связь, Подарки, Зарплата, Инвестиции, Фриланс, Переводы, Другое]
- description: краткое описание из текста (например "баланс", "кофе", "такси")

ВАЖНОЕ ПРАВИЛО ПРО БАЛАНС:
Если пользователь говорит "мой баланс X", "у меня есть X", "остаток X" — это ДОХОД (income).
Категория в таком случае — "Другое", описание — "Начальный баланс".

Если в тексте вообще нет чисел — верни пустой список transactions.

Верни результат СТРОГО в формате JSON:
{{
  "transactions": [
    {{
      "type": "income",
      "amount": 300000,
      "currency": "UZS",
      "category": "Другое",
      "description": "Начальный баланс"
    }}
  ]
}}
"""
        logger.info(f"Parsing text with AI: {text}")
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
        logger.info(f"AI Response: {content}")
        
        if not content:
            raise ValueError("Empty response from LLM")
            
        try:
            parsed_json = json.loads(content)
            return ParsedTransactions.model_validate(parsed_json)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"JSON validation error: {e}, content: {content}")
            raise
