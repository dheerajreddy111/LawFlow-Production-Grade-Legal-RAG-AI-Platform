"""Append-only event log for query analytics."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QueryEvent(Base):
    """One row per resolved /query request.

    Recorded after orchestration resolves, regardless of route taken.
    Stores the bare minimum needed for time-series + distribution
    aggregations — query text is *not* persisted to keep the table
    cheap and avoid PII reuse risk.
    """

    __tablename__ = "query_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    # user_id is nullable so historic events survive a user being deleted
    # (FK cascade is intentionally NOT set — we want forensic continuity).
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The opaque session id the SPA sends — useful for follow-up rate
    # but not joinable to anything.
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    intent: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    route: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    has_error: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Short snippet of the query (first 160 chars) — enough to recognise
    # "what was this" in the recent-failures panel without storing the
    # entire input. Truncated by the writer, not the DB.
    query_preview: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Domain / intent metadata we already compute; useful as a secondary
    # dimension in the distribution chart.
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )

    # Index helper for time-bucket scans
    __table_args__ = ()


__all__ = ["QueryEvent"]
