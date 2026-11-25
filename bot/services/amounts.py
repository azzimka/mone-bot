"""Strict decimal amount parsing for expense entries."""

import re
from decimal import Decimal, InvalidOperation

from bot.services.i18n import tr

MAX_AMOUNT = Decimal("9999999999999.99")


class AmountParseError(ValueError):
    """Raised when an amount string cannot be parsed safely as a decimal."""


def parse_amount(value: str) -> Decimal:
    value = re.sub(r"[\s\u00a0\u202f]", "", value)
    if not value or len(value) > 40:
        raise AmountParseError(tr("Не указана корректная сумма."))
    # Comma is a decimal separator; use spaces for thousands. Reject ambiguity.
    if "," in value:
        if "." in value or value.count(",") != 1 or len(value.rsplit(",", 1)[1]) > 2:
            raise AmountParseError(tr("Неоднозначная сумма: используйте 1 234,56 или 1234.56."))
        value = value.replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d{1,2})?", value):
        raise AmountParseError(tr("Сумма должна быть числом с максимум двумя знаками после запятой."))
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise AmountParseError(tr("Некорректная сумма.")) from exc
    if not amount.is_finite() or abs(amount) > MAX_AMOUNT:
        raise AmountParseError(tr("Сумма выходит за допустимый диапазон."))
    return amount
