"""Database repositories for User, Transaction, and Category entities."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import delete as sql_delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.category import Category
from bot.models.transaction import Transaction
from bot.models.user import User

DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("🍔", "Еда"),
    ("🚕", "Транспорт"),
    ("🏠", "Жильё"),
    ("👕", "Одежда"),
    ("🎮", "Развлечения"),
    ("💊", "Здоровье"),
    ("📚", "Образование"),
    ("💼", "Работа"),
    ("📱", "Связь"),
    ("🎁", "Подарки"),
    ("❓", "Другое"),
    ("💰", "Зарплата"),
    ("📈", "Инвестиции"),
    ("🎯", "Фриланс"),
    ("💸", "Переводы"),
    ("⚖️", "Сверка"),
]

# Emoji map for category icons in reports
CATEGORY_ICONS: dict[str, str] = {icon: name for icon, name in DEFAULT_CATEGORIES}
CATEGORY_ICON_MAP: dict[str, str] = {name: icon for icon, name in DEFAULT_CATEGORIES}


class UserRepository:
    """Repository for managing User entities."""

    @staticmethod
    async def set_language(session: AsyncSession, telegram_id: int, language: str) -> User:
        if language not in {"uz", "ru"}:
            raise ValueError("Unsupported language")
        user = await UserRepository.get_or_create(session, telegram_id)
        user.language = language
        await session.flush()
        return user

    @staticmethod
    async def get_or_create(
        session: AsyncSession,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
    ) -> User:
        """Get an existing user by Telegram ID or create a new one."""
        stmt = select(User).where(User.telegram_id == telegram_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
            )
            session.add(user)
            await session.flush()
        else:
            updated = False
            if username is not None and user.username != username:
                user.username = username
                updated = True
            if first_name is not None and user.first_name != first_name:
                user.first_name = first_name
                updated = True
            if updated:
                await session.flush()

        return user


class TransactionRepository:
    """Repository for managing Transaction entities."""

    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int,
        type: str,
        amount: Decimal | float | int,
        currency: str = "UZS",
        category: Optional[str] = None,
        description: Optional[str] = None,
        voice_text: Optional[str] = None,
        date: Optional[date] = None,
    ) -> Transaction:
        """Create and persist a new transaction."""
        if date is None:
            date = datetime.now().date()

        transaction = Transaction(
            user_id=user_id,
            type=type,
            amount=Decimal(str(amount)),
            currency=currency,
            category=category,
            description=description,
            voice_text=voice_text,
            date=date,
        )
        session.add(transaction)
        await session.flush()
        return transaction

    @staticmethod
    async def get_by_period(
        session: AsyncSession,
        user_id: int,
        start_date: date,
        end_date: date,
        tx_type: Optional[str] = None,
    ) -> list[Transaction]:
        """Get all transactions for a user within a specified date range."""
        stmt = (
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.date >= start_date,
                Transaction.date <= end_date,
            )
            .order_by(Transaction.date.asc(), Transaction.id.asc())
        )
        if tx_type:
            stmt = stmt.where(Transaction.type == tx_type)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_summary_by_category(
        session: AsyncSession,
        user_id: int,
        start_date: date,
        end_date: date,
        tx_type: str = "expense",
    ) -> list[tuple[str, Decimal]]:
        """Get summary total grouped by category for a user within a period."""
        stmt = (
            select(
                func.coalesce(Transaction.category, "Другое").label("category"),
                func.sum(Transaction.amount).label("total_amount"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.type == tx_type,
                Transaction.date >= start_date,
                Transaction.date <= end_date,
            )
            .group_by(Transaction.category)
            .order_by(func.sum(Transaction.amount).desc())
        )
        result = await session.execute(stmt)
        return [(str(row[0]), Decimal(str(row[1]))) for row in result.all()]

    @staticmethod
    async def get_daily_totals(
        session: AsyncSession,
        user_id: int,
        start_date: date,
        end_date: date,
        tx_type: str = "expense",
    ) -> list[tuple[date, Decimal]]:
        """Get daily total amounts grouped by date within a period."""
        stmt = (
            select(
                Transaction.date.label("tx_date"),
                func.sum(Transaction.amount).label("total_amount"),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.type == tx_type,
                Transaction.date >= start_date,
                Transaction.date <= end_date,
            )
            .group_by(Transaction.date)
            .order_by(Transaction.date.asc())
        )
        result = await session.execute(stmt)
        return [(row[0], Decimal(str(row[1]))) for row in result.all()]

    @staticmethod
    async def get_total(
        session: AsyncSession,
        user_id: int,
        start_date: date,
        end_date: date,
        tx_type: str,
    ) -> Decimal:
        """Get total sum of transactions for a user within a period by type."""
        stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.type == tx_type,
            Transaction.date >= start_date,
            Transaction.date <= end_date,
        )
        result = await session.execute(stmt)
        total = result.scalar()
        return Decimal(str(total)) if total is not None else Decimal("0.00")

    @staticmethod
    async def delete(
        session: AsyncSession,
        transaction_id: int,
        user_id: int,
    ) -> bool:
        """Delete a transaction by ID for a specific user."""
        stmt = sql_delete(Transaction).where(
            Transaction.id == transaction_id,
            Transaction.user_id == user_id,
        )
        result = await session.execute(stmt)
        await session.flush()
        return result.rowcount > 0


class CategoryRepository:
    """Repository for managing Category entities."""

    @staticmethod
    async def get_defaults(session: AsyncSession) -> list[Category]:
        """Retrieve all default system categories."""
        stmt = (
            select(Category)
            .where(Category.is_default.is_(True))
            .order_by(Category.id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def seed_defaults(session: AsyncSession) -> list[Category]:
        """Seed default categories into the database if they do not exist."""
        stmt = select(Category.name).where(
            Category.is_default.is_(True),
            Category.user_id.is_(None),
        )
        result = await session.execute(stmt)
        existing_names = set(result.scalars().all())

        created: list[Category] = []
        for icon, name in DEFAULT_CATEGORIES:
            if name not in existing_names:
                category = Category(
                    name=name,
                    icon=icon,
                    user_id=None,
                    is_default=True,
                )
                session.add(category)
                created.append(category)

        if created:
            await session.flush()

        return created
