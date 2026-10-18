"""Free CBU reference rates with durable caching and exact Decimal conversions."""
import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bot.models import ExchangeRateSnapshot

SOURCE = 'CBU'
SOURCE_URL = 'https://cbu.uz/uz/arkhiv-kursov-valyut/veb-masteram/'
API_URL = 'https://cbu.uz/uz/arkhiv-kursov-valyut/json/all/'


class RatesUnavailable(ValueError):
    pass


class UnknownCurrency(ValueError):
    pass


def cbu_today() -> date:
    return datetime.now(ZoneInfo('Asia/Tashkent')).date()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


async def fetch_cbu(day: date):
    # Only the date is sent. No account, transaction, Telegram ID or token leaves Mone.
    async with httpx.AsyncClient(timeout=8) as client:
        async with client.stream('GET', f'{API_URL}{day.isoformat()}/') as response:
            response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 1_048_576:
                    raise RatesUnavailable('Kurslar javobi juda katta.')
    return json.loads(content)


def parse_cbu(payload, requested: date) -> tuple[date, dict[str, Decimal]]:
    if not isinstance(payload, list) or not 1 <= len(payload) <= 300:
        raise RatesUnavailable('Kurslar formati noto‘g‘ri.')
    rates = {'UZS': Decimal(1)}
    dates = set()
    try:
        for row in payload:
            code = row['Ccy']
            nominal, amount = Decimal(str(row['Nominal'])), Decimal(str(row['Rate']))
            effective = datetime.strptime(row['Date'], '%d.%m.%Y').date()
            if (not re.fullmatch(r'[A-Z]{3}', code) or code in rates
                    or not nominal.is_finite() or not amount.is_finite()
                    or not 0 < nominal <= 10**9 or not 0 < amount <= 10**15
                    or effective > requested):
                raise ValueError('Invalid rate')
            rates[code] = amount / nominal
            dates.add(effective)
        if len(dates) != 1 or 'USD' not in rates:
            raise ValueError('Incomplete or mixed-date rates')
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as error:
        raise RatesUnavailable('Kurslar formati noto‘g‘ri.') from error
    return dates.pop(), rates


@dataclass(frozen=True)
class RateBook:
    requested_date: date
    effective_date: date
    fetched_at: datetime
    rates: dict[str, Decimal]
    stale: bool = False

    def ratio(self, source: str, destination: str) -> Decimal:
        try:
            return self.rates[source] / self.rates[destination]
        except KeyError as error:
            raise UnknownCurrency('Bu valyuta uchun Markaziy bank kursi topilmadi.') from error

    def convert(self, amount: Decimal, source: str, destination: str) -> Decimal:
        return amount * self.ratio(source, destination)

    def metadata(self) -> dict:
        return {'source': SOURCE, 'source_url': SOURCE_URL,
                'requested_date': self.requested_date.isoformat(),
                'effective_date': self.effective_date.isoformat(),
                'fetched_at': utc(self.fetched_at).isoformat(), 'stale': self.stale}


def as_book(record: ExchangeRateSnapshot, requested: date, stale=False) -> RateBook:
    return RateBook(requested, record.effective_date, record.fetched_at,
                    {key: Decimal(value) for key, value in json.loads(record.rates_json).items()}, stale)


class ExchangeRateService:
    def __init__(self, fetcher=None):
        self.fetcher = fetcher
        self.lock = asyncio.Lock()
        self.retry_after: dict[date, datetime] = {}

    async def get(self, session, requested: date | None = None) -> RateBook:
        requested = requested or cbu_today()
        now = datetime.now(timezone.utc)
        async with self.lock:
            record = await session.get(ExchangeRateSnapshot, requested, populate_existing=True)
            if record and (requested < cbu_today() or now - utc(record.fetched_at) < timedelta(hours=6)):
                return as_book(record, requested)
            if self.retry_after.get(requested, now) <= now:
                try:
                    effective, rates = parse_cbu(await (self.fetcher or fetch_cbu)(requested), requested)
                    values = dict(effective_date=effective,
                                  rates_json=json.dumps({key: str(value) for key, value in rates.items()}),
                                  fetched_at=now)
                    if record:
                        for key, value in values.items():
                            setattr(record, key, value)
                    else:
                        try:
                            async with session.begin_nested():
                                record = ExchangeRateSnapshot(requested_date=requested, **values)
                                session.add(record)
                                await session.flush()
                        except IntegrityError:
                            # Another API process stored the same public snapshot first.
                            record = await session.get(ExchangeRateSnapshot, requested, populate_existing=True)
                    await session.flush()
                    self.retry_after.pop(requested, None)
                    return as_book(record, requested)
                except (httpx.HTTPError, ValueError, TypeError, ArithmeticError):
                    self.retry_after[requested] = now + timedelta(minutes=5)
            # Historical conversions must never silently substitute another day's rate.
            if requested == cbu_today():
                fallback = (await session.execute(select(ExchangeRateSnapshot).where(
                    ExchangeRateSnapshot.requested_date <= requested,
                    ExchangeRateSnapshot.requested_date >= requested - timedelta(days=7),
                    ExchangeRateSnapshot.effective_date >= requested - timedelta(days=7)
                ).order_by(ExchangeRateSnapshot.requested_date.desc()).limit(1))).scalar_one_or_none()
                if fallback:
                    return as_book(fallback, requested, stale=True)
            raise RatesUnavailable('Kurslar hozir olinmadi. Keyinroq urinib ko‘ring.')


def money_round(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
