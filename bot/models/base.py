"""Declarative Base class for SQLAlchemy models."""

from datetime import datetime

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models in Cash Control."""
    pass
