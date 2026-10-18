"""Category database model."""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.user import User


class Category(Base):
    """Database model representing an expense or income category."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("name", "user_id", name="uq_categories_name_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    parent_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    user: Mapped[Optional["User"]] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<Category(id={self.id}, name={self.name!r}, icon={self.icon!r}, "
            f"user_id={self.user_id}, is_default={self.is_default})>"
        )
