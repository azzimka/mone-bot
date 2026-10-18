from bot.services.i18n import tr, button_variants
"""Strict CSV validation and local categorization; no financial data sent to AI."""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MAX_FILE_BYTES = 1024 * 1024
MAX_ROWS = 2000
MAX_AMOUNT = Decimal("9999999999999.99")


class CsvImportError(ValueError):
    """A file cannot be safely imported."""


def normalize(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


ALIASES = {
    "date": ("date", "transaction date", "дата", "sana"),
    "amount": ("amount", "sum", "сумма", "summa", "miqdor"),
    "type": ("type", "transaction type", "тип", "тип операции", "tur", "turi"),
    "income": ("income", "приход", "доход", "kirim"),
    "expense": ("expense", "расход", "chiqim"),
    "currency": ("currency", "валюта", "valyuta"),
    "category": ("category", "категория", "kategoriya", "toifa"),
    "description": ("description", "note", "notes", "comment", "описание", "комментарий", "izoh", "tavsif"),
}
HEADER_MAP = {normalize(alias): field for field, aliases in ALIASES.items() for alias in aliases}
TYPE_MAP = {
    **{normalize(v): "income" for v in ("income", "credit", "deposit", "доход", "приход", "пополнение", "kirim", "+") if normalize(v)},
    **{normalize(v): "expense" for v in ("expense", "debit", "withdrawal", "расход", "chiqim", "xarajat")},
}

# Match words/stems, not arbitrary substrings (e.g. "bar" inside "Barbara").
CATEGORY_RULES = (
    ("Зарплата", r"salary|payroll|зарплат\w*|oylik|maosh\w*"),
    ("Фриланс", r"freelanc\w*|фриланс\w*"),
    ("Инвестиции", r"invest\w*|инвест\w*|dividend\w*|дивиденд\w*"),
    ("Транспорт", r"taxi|такси|yandex|яндекс|uber|автобус\w*|метро|transport\w*|bus|benzin|бензин|yoqilg\w*"),
    ("Еда", r"food|grocer\w*|кофе|кофей\w*|cafe|café|coffee|lunch|dinner|restaurant\w*|кафе|ресторан\w*|продукт\w*|обед\w*|ужин\w*|ovqat\w*|oziq\w*|kofe|korzinka|makro|non"),
    ("Жильё", r"rent|utility|utilities|аренд\w*|квартир\w*|коммунал\w*|ijara|kommunal\w*|электр\w*"),
    ("Здоровье", r"health\w*|pharmacy|medicine|hospital|аптек\w*|лекарств\w*|врач\w*|dorixona|dori|shifokor\w*"),
    ("Образование", r"education|course\w*|tuition|book\w*|курс\w*|обучен\w*|книг\w*|kitob\w*|talim|maktab\w*"),
    ("Связь", r"internet|mobile|phone|интернет|телефон\w*|связь|aloqa|beeline|ucell|uzmobile"),
    ("Одежда", r"cloth\w*|shoes|одежд\w*|обув\w*|kiyim\w*|poyabzal\w*"),
    ("Развлечения", r"entertain\w*|cinema|game\w*|кино\w*|игр\w*|netflix|spotify"),
    ("Подарки", r"gift\w*|подар\w*|sovga\w*"),
    ("Переводы", r"transfer\w*|перевод\w*|otkazma\w*"),
)
CATEGORY_NAMES = {normalize(v): v for v in (
    "Еда", "Транспорт", "Жильё", "Одежда", "Развлечения", "Здоровье",
    "Образование", "Работа", "Связь", "Подарки", "Другое", "Зарплата",
    "Инвестиции", "Фриланс", "Переводы", "Сверка",
)}
CATEGORY_ALIASES = dict(zip(
    ("food", "transport", "housing", "clothing", "entertainment", "health", "education", "work", "communication", "gifts", "other", "salary", "investments", "freelance", "transfers"),
    ("Еда", "Транспорт", "Жильё", "Одежда", "Развлечения", "Здоровье", "Образование", "Работа", "Связь", "Подарки", "Другое", "Зарплата", "Инвестиции", "Фриланс", "Переводы"),
))


def categorize(category: str, description: str) -> str:
    if category:
        if len(category) > 100:
            raise CsvImportError(tr('Категория длиннее 100 символов.'))
        return CATEGORY_NAMES.get(normalize(category), CATEGORY_ALIASES.get(normalize(category), category))
    for name, pattern in CATEGORY_RULES:
        if re.search(rf"\b(?:{pattern})\b", description.casefold()):
            return name
    return "Другое"


@dataclass(frozen=True)
class CsvTransaction:
    date: date
    type: str
    amount: Decimal
    currency: str
    category: str
    description: str

    def to_dict(self) -> dict:
        return {"date": self.date.isoformat(), "type": self.type, "amount": str(self.amount),
                "currency": self.currency, "category": self.category, "description": self.description}


@dataclass(frozen=True)
class CsvPreview:
    source_text: str
    transactions: list[CsvTransaction]
    inferred_types: bool


def parse_amount(value: str) -> Decimal:
    value = re.sub(r"[\s\u00a0\u202f]", "", value)
    if not value or len(value) > 40:
        raise CsvImportError(tr('Не указана корректная сумма.'))
    # Comma is a decimal separator; use spaces for thousands. Reject ambiguity.
    if "," in value:
        if "." in value or value.count(",") != 1 or len(value.rsplit(",", 1)[1]) > 2:
            raise CsvImportError(tr('Неоднозначная сумма: используйте 1 234,56 или 1234.56.'))
        value = value.replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d{1,2})?", value):
        raise CsvImportError(tr('Сумма должна быть числом с максимум двумя знаками после запятой.'))
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise CsvImportError(tr('Некорректная сумма.')) from exc
    if not amount.is_finite() or abs(amount) > MAX_AMOUNT:
        raise CsvImportError(tr('Сумма выходит за допустимый диапазон.'))
    return amount


def parse_date(value: str) -> date:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise CsvImportError(tr('Дата должна быть YYYY-MM-DD или DD.MM.YYYY.'))


def parse_csv(data: bytes, default_currency: str = "UZS") -> CsvPreview:
    if not data or len(data) > MAX_FILE_BYTES:
        raise CsvImportError(tr('Отправьте непустой CSV размером до 1 МБ.'))
    source = None
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            source = data.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    if source is None or "\x00" in source:
        raise CsvImportError(tr('Нужен текстовый CSV в UTF-8 или Windows-1251.'))
    if len(source.splitlines()) > MAX_ROWS * 10:
        raise CsvImportError(tr('Слишком много строк. Максимум {p1} операций.' ,p1=f'{MAX_ROWS}'))
    first_line = next((line for line in source.splitlines() if line.strip()), "")
    try:
        dialect = csv.Sniffer().sniff(first_line, delimiters=",;\t")
        reader = csv.reader(io.StringIO(source.lstrip("\r\n")), dialect, strict=True)
        headers = next(reader)
        mapping = {}
        for index, header in enumerate(headers):
            field = HEADER_MAP.get(normalize(header))
            if field:
                if field in mapping:
                    raise CsvImportError(tr('Повторяющийся столбец: {p1}.' ,p1=f'{field}'))
                mapping[field] = index
        split_amounts = "amount" not in mapping and {"income", "expense"} <= mapping.keys()
        if "date" not in mapping or ("amount" not in mapping and not split_amounts):
            raise CsvImportError(tr('Нужны столбцы date / дата / sana и amount / сумма / summa (или отдельные income / expense, kirim / chiqim). Пример: /import.'))
        transactions = []
        errors = []
        inferred_types = not split_amounts and "type" not in mapping
        for values in reader:
            if not any(v.strip() for v in values):
                continue
            if len(transactions) + len(errors) >= MAX_ROWS:
                raise CsvImportError(tr('Максимум {p1} операций в одном файле.' ,p1=f'{MAX_ROWS}'))
            try:
                if len(values) != len(headers):
                    raise CsvImportError(tr('Число столбцов не совпадает с заголовком.'))
                def get(field):
                    return values[mapping[field]].strip() if field in mapping else ""
                tx_date = parse_date(get("date"))
                if split_amounts:
                    income = parse_amount(get("income") or "0")
                    expense = parse_amount(get("expense") or "0")
                    if income < 0 or expense < 0 or (income > 0) == (expense > 0):
                        raise CsvImportError(tr('Укажите положительную сумму только в одном из столбцов income / expense.'))
                    tx_type, amount = ("income", income) if income else ("expense", expense)
                else:
                    amount = parse_amount(get("amount"))
                    raw_type = get("type")
                    if "type" in mapping:
                        tx_type = TYPE_MAP.get(normalize(raw_type))
                        if tx_type is None:
                            raise CsvImportError(tr('Тип: income / expense, kirim / chiqim или доход / расход.'))
                        if tx_type == "income" and amount < 0:
                            raise CsvImportError(tr('Отрицательная сумма противоречит типу income.'))
                    else:
                        tx_type = "expense" if amount < 0 else "income"
                    amount = abs(amount)
                if amount == 0:
                    raise CsvImportError(tr('Нулевая сумма не является операцией.'))
                currency = (get("currency") or default_currency).upper()
                # Existing bot reports sum one currency. Never silently mix imported currencies.
                if currency != default_currency.upper():
                    raise CsvImportError(tr('Бот ведёт учёт в {p1}; сначала конвертируйте эту операцию.' ,p1=f'{default_currency}'))
                description = get("description")
                if len(description) > 2000:
                    raise CsvImportError(tr('Описание длиннее 2000 символов.'))
                category = categorize(get("category"), description)
                transactions.append(CsvTransaction(tx_date, tx_type, amount, currency, category, description))
            except CsvImportError as exc:
                errors.append(tr('Строка {p1}: {p3}' ,p1=f'{reader.line_num}', p3=f'{exc}'))
        if errors:
            raise CsvImportError(tr('Ничего не импортировано. Исправьте CSV:\n') + "\n".join(errors[:5])
                                 + (tr('\nВсего строк с ошибками: {p1}.' ,p1=f'{len(errors)}') if len(errors) > 5 else ""))
        if not transactions:
            raise CsvImportError(tr('В файле нет операций.'))
        return CsvPreview(source, transactions, inferred_types)
    except (csv.Error, StopIteration) as exc:
        raise CsvImportError(tr('Не удалось прочитать CSV. Разделитель: запятая, точка с запятой или табуляция.')) from exc


def format_preview(preview: CsvPreview) -> str:
    txs = preview.transactions
    totals = {kind: sum((tx.amount for tx in txs if tx.type == kind), Decimal(0))
              for kind in ("income", "expense")}
    currency = txs[0].currency
    categories = {}
    for tx in txs:
        categories[tx.category] = categories.get(tx.category, 0) + 1
    lines = [tr('CSV: {p1} операций' ,p1=f'{len(txs)}'), tr('Период: {p1} — {p3}' ,p1=f'{min((t.date for t in txs))}', p3=f'{max((t.date for t in txs))}'),
             tr('Кирим / Доход: {p1} {p3}' ,p1=f"{totals['income']:,.2f}", p3=f'{currency}'),
             tr('Чиқим / Расход: {p1} {p3}' ,p1=f"{totals['expense']:,.2f}", p3=f'{currency}'), "", tr('Категории (число операций):')]
    for category, count in sorted(categories.items(), key=lambda item: -item[1])[:10]:
        lines.append(f"• {category[:80]}: {count}")
    if len(categories) > 10:
        lines.append(tr('…ещё {p1} категорий.' ,p1=f'{len(categories) - 10}'))
    lines.extend(["", tr('Первые операции:')])
    for tx in txs[:5]:
        sign = "+" if tx.type == "income" else "−"
        lines.append(f"{tx.date}: {sign}{tx.amount} {tx.currency} · {tx.category[:60]} · {tx.description[:80]}")
    if preview.inferred_types:
        lines.extend(["", tr('Внимание: столбца type нет. Положительные суммы — доход, отрицательные — расход.')])
    lines.extend(["", tr('Категории из файла сохранены; пустые определены по описанию, неизвестные — «Другое».'),
                  tr('Проверьте суммы, типы и категории перед импортом. Подтверждение действует 24 часа.')])
    return "\n".join(lines)
