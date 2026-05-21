"""DeclarativeBase shared by every ORM model."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base — keep empty; per-model concerns live on the models."""
