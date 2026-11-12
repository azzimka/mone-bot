"""Database model for AI financial advisor conversation history."""

from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class AdvisorMessage(Base):
    """Stores consultation turns for the bot's read-only AI financier mode."""

    __tablename__ = "advisor_messages"
    __table_args__ = (
        Index("ix_advisor_messages_user_id_id", "user_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # 'user' or 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
