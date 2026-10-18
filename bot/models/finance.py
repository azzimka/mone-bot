"""Accounts, transfers and opt-in financial automation."""
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from bot.models.base import Base

class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_account_owner_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(10), default="cash")
    currency: Mapped[str] = mapped_column(String(10))
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(15,2), default=Decimal(0))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

class Transfer(Base):
    __tablename__ = "account_transfers"
    __table_args__ = (UniqueConstraint("user_id", "request_key", name="uq_transfer_request"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    destination_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    source_amount: Mapped[Decimal] = mapped_column(Numeric(15,2))
    destination_amount: Mapped[Decimal] = mapped_column(Numeric(15,2))
    date: Mapped[date] = mapped_column(Date)
    description: Mapped[str] = mapped_column(String(2000), default="")
    request_key: Mapped[str] = mapped_column(String(64))

class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("user_id", "month", "category", "currency", name="uq_budget_scope"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    month: Mapped[str] = mapped_column(String(7))
    category: Mapped[str] = mapped_column(String(100), default="")
    currency: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(15,2))
    notify_telegram: Mapped[bool] = mapped_column(Boolean, default=False)

class BudgetAlert(Base):
    __tablename__ = "budget_alerts"
    __table_args__ = (UniqueConstraint("budget_id", "level", name="uq_budget_alert_level"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id", ondelete="CASCADE"))
    level: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

class RecurringRule(Base):
    __tablename__ = "recurring_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    type: Mapped[str] = mapped_column(String(10))
    amount: Mapped[Decimal] = mapped_column(Numeric(15,2))
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(2000), default="")
    frequency: Mapped[str] = mapped_column(String(10))
    next_date: Mapped[date] = mapped_column(Date)
    anchor_day: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class RecurringOccurrence(Base):
    __tablename__ = "recurring_occurrences"
    __table_args__ = (UniqueConstraint("rule_id", "date", name="uq_recurring_occurrence"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("recurring_rules.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True)

class RestoreLog(Base):
    __tablename__ = "restore_logs"
    __table_args__ = (UniqueConstraint("user_id", "file_hash", name="uq_restore_file"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    file_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
