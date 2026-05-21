"""Minimal async-job persistence.

Foundational only — no executor, no queue, no admin UI. Future async
work (long-running evaluation runs, ingestion reprocessing, cleanup
sweeps, periodic aggregations) records its lifecycle through this
module so the operator can observe what's in flight.

Stays in-process by design: persistence is in the existing SQLite,
and any "runner" is just a coroutine the caller schedules with
``asyncio.create_task``. We are not introducing Celery, Redis, or
distributed workers.

Public surface:

- ``JobStatus``      enum: queued / running / completed / failed
- ``Job``            SQLAlchemy model
- ``JobOut``, ``JobCreate``  Pydantic schemas
- ``create_job``, ``mark_running``, ``mark_completed``, ``mark_failed``
  async persistence helpers
"""

from app.jobs.models import Job
from app.jobs.persistence import (
    create_job,
    mark_completed,
    mark_failed,
    mark_running,
)
from app.jobs.schemas import JobCreate, JobOut
from app.jobs.types import JobStatus

__all__ = [
    "Job",
    "JobCreate",
    "JobOut",
    "JobStatus",
    "create_job",
    "mark_completed",
    "mark_failed",
    "mark_running",
]
