"""Persistent evaluation-run history.

Mirrors :mod:`app.analytics.models` in approach: append-only, no
UPDATE; the full :class:`EvaluationReport` is persisted as JSON in
``report_json`` so the admin detail view can render per-row breakdowns
without re-running the benchmark.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvaluationRun(Base):
    """One execution of the evaluation harness.

    Aggregate metrics are denormalised into columns so the history page
    can sort/filter without parsing JSON. The full report (with per-row
    detail) lives in ``report_json`` and is fetched only on the detail
    view.
    """

    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Operator-facing label. Defaults to the dataset filename when the
    # client omits a name.
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    dataset_filename: Mapped[str] = mapped_column(String(200), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scored_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Mean of each metric across scored rows. Min / max can be derived
    # from report_json on demand; we only denormalise the dimensions the
    # history table needs to sort by.
    f1_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cosine_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    keyword_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retrieval_mean: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # FK NOT cascaded — we want forensic continuity if a user is removed.
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    # Full EvaluationReport.model_dump_json(). Bounded by upload size +
    # row cap, not by us — SQLite handles multi-MB TEXT cells fine.
    report_json: Mapped[str] = mapped_column(Text, nullable=False, default="")


__all__ = ["EvaluationRun"]
