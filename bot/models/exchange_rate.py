"""Public central-bank data only; never contains a user's ledger."""
from datetime import date, datetime
from sqlalchemy import Date, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from bot.models.base import Base


class ExchangeRateSnapshot(Base):
    __tablename__ = 'exchange_rate_snapshots'

    requested_date: Mapped[date] = mapped_column(Date, primary_key=True)
    effective_date: Mapped[date] = mapped_column(Date)
    rates_json: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
