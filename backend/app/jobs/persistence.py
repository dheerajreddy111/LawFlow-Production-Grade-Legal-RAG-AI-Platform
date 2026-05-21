"""Async persistence helpers for the jobs table.

All four helpers commit immediately so the caller can ``await
create_job(...)`` from a request handler, hand the id off to a
background task, and trust that the row is durable. Errors from the
DB layer propagate — unlike the analytics writer, *callers* need to
know if the lifecycle row was not recorded.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import session_scope
from app.jobs.models import Job
from app.jobs.schemas import JobCreate, JobOut
from app.jobs.types import JobStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def create_job(payload: JobCreate) -> JobOut:
    """Insert a new ``queued`` job and return its row."""
    async with session_scope() as session:
        row = Job(
            type=payload.type[:64],
            status=JobStatus.QUEUED.value,
            payload_json=payload.payload_as_json(),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return JobOut.from_row(row)


async def mark_running(job_id: int) -> JobOut:
    """Transition a job to ``running`` and record the start time."""
    async with session_scope() as session:
        row = await session.get(Job, job_id)
        if row is None:
            raise LookupError(f"Job {job_id} not found")
        row.status = JobStatus.RUNNING.value
        row.started_at = _utcnow()
        await session.commit()
        await session.refresh(row)
        return JobOut.from_row(row)


async def mark_completed(job_id: int, result: dict | None = None) -> JobOut:
    """Transition a job to ``completed`` and stamp the result."""
    import json

    async with session_scope() as session:
        row = await session.get(Job, job_id)
        if row is None:
            raise LookupError(f"Job {job_id} not found")
        row.status = JobStatus.COMPLETED.value
        row.completed_at = _utcnow()
        row.result_json = json.dumps(result, separators=(",", ":")) if result else None
        row.error = None
        await session.commit()
        await session.refresh(row)
        return JobOut.from_row(row)


async def mark_failed(job_id: int, error: str) -> JobOut:
    """Transition a job to ``failed`` and stamp the error message."""
    async with session_scope() as session:
        row = await session.get(Job, job_id)
        if row is None:
            raise LookupError(f"Job {job_id} not found")
        row.status = JobStatus.FAILED.value
        row.completed_at = _utcnow()
        row.error = error[:4000] if error else None  # bounded so a stack trace can't blow the row
        await session.commit()
        await session.refresh(row)
        return JobOut.from_row(row)


# ── Read helpers (intentionally tiny — admin UI ships later) ───────────────


async def get_job(job_id: int) -> JobOut | None:
    async with session_scope() as session:
        row = await session.get(Job, job_id)
        return JobOut.from_row(row) if row is not None else None


async def list_recent_jobs(limit: int = 50) -> list[JobOut]:
    async with session_scope() as session:
        stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return [JobOut.from_row(r) for r in rows]


__all__ = [
    "create_job",
    "get_job",
    "list_recent_jobs",
    "mark_completed",
    "mark_failed",
    "mark_running",
]
