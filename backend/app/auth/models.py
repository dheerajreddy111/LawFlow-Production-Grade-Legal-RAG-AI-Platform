"""ORM models for users and refresh tokens.

Refresh tokens are stored hashed (sha256) so a DB leak does not yield
session-stealing material. Access tokens are stateless JWTs; revocation
applies to refresh tokens only.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default=UserRole.USER.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_refresh_token_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # sha256 hex digest of the raw refresh token. Never store the raw token.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    jti: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")

    @property
    def is_active(self) -> bool:
        if self.revoked_at is not None:
            return False
        # SQLite strips tzinfo on read even when the column is
        # ``DateTime(timezone=True)``; centralised in app.utils.time.as_utc.
        from app.utils.time import as_utc

        return as_utc(self.expires_at) > _utcnow()
