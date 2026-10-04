import asyncio
import logging
import json
from typing import Literal, Optional
from pydantic import BaseModel, ValidationError
from groq import Groq

logger = logging.getLogger(__name__)

class ParsedTransaction(BaseModel):
    type: Literal["income", "expense", "reconcile"]
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
Вы умный финансовый ассистент. Ваша задача - извлекать финансовые транзакции и операции из сообщений пользователя.

Каждая транзакция должна содержать: 
- type:
    * "expense" — трата, покупка, оплата (еда, такси, кафе и т.д.)
    * "income" — доход (зарплата, приход, вернули долг, подарок)
    * "reconcile" — сверка / установка фактического баланса. Используется, когда пользователь сообщает СВОЙ ТЕКУЩИЙ ОСТАТОК / БАЛАНС (например: "мой баланс 50 тысяч", "баланс 50к", "у меня сейчас 50 000 сум", "сведи баланс на 50 000", "meni balansim 50 ming", "balans 50000"). Если пользователь перечисляет суммы на разных картах/в кармане ("на карте 30к и в кармане 20к", "на одной карте 25к, на второй 15к и 10к налик"), сложи их в одну общую сумму amount.
- amount: число (сумма). Обязательно число без пробелов.
- currency: валюта. Если не указана, используй '{default_currency}'
- category: выбери наиболее подходящую категорию. Для сверки баланса укажи "Сверка". Для остальных: [Еда, Транспорт, Жильё, Одежда, Развлечения, Здоровье, Образование, Работа, Связь, Подарки, Зарплата, Инвестиции, Фриланс, Переводы, Другое]
- description: краткое описание из текста (например "сверка баланса", "кофе", "такси")

Если в тексте вообще нет финансовых операций или чисел — верни пустой список transactions: {{"transactions": []}}.

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
