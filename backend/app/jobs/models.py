"""Job row.

The minimum schema needed to observe an async unit of work without
imposing any specific executor. ``type`` is a free-form string so
callers can name their own job types (``evaluation_run``,
``ingest_url``, ``cleanup_query_events``, ...) — the table doesn't
care.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.jobs.types import JobStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    """One unit of async work tracked in the DB.

    Lifecycle (any path through the status graph is valid):

        queued ──► running ──► completed
                      └─────► failed
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=JobStatus.QUEUED.value,
        index=True,
    )
    # JSON-encoded inputs (text rather than JSON column type so SQLite
    # + Postgres share the same migration).
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-encoded output on COMPLETED; absent on FAILED / QUEUED.
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Human-readable error on FAILED.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["Job"]
