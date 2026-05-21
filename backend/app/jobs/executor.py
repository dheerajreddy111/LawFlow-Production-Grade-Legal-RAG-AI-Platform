"""Background job executor.

Schedules a coroutine on the running event loop, transitions the job row
through ``queued → running → completed`` (or ``failed``), and surfaces
the eventual result via the existing :mod:`app.jobs.persistence`
helpers. There is no separate worker process — we deliberately stay
in-process so SQLite is enough and a separate Redis/Celery deploy isn't
needed.

The executor is *cooperative*: jobs share the API process's event loop.
Long-running CPU-bound work should still go through ``asyncio.to_thread``
inside the handler — this module won't help with that.

What it gives the caller
------------------------
- A typed registration table: handlers register by job *type*.
- A single ``enqueue()`` entry point that creates the row + schedules
  the handler. Returns immediately with the job id.
- Lifecycle bookkeeping — running / completed / failed — wired through
  :mod:`app.jobs.persistence` so the admin Jobs page sees the same
  status the executor sees.

What it does NOT do
-------------------
- Retries. A failed job is final.
- Cross-process / cross-restart resume. A job that was running when
  the API exits stays at ``running`` forever; an operator can reaper
  via the cleanup module (``cleanup_stale_jobs``).
- Priority queues / scheduling. ``enqueue`` runs the work immediately.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from app.jobs.persistence import (
    create_job,
    mark_completed,
    mark_failed,
    mark_running,
)
from app.jobs.schemas import JobCreate, JobOut

logger = logging.getLogger(__name__)

# A handler is an async callable that takes the decoded payload (any
# JSON-serialisable shape) and returns the JSON-serialisable result
# (None when the job has no result). The handler is responsible for
# its own structured logging; the executor only handles lifecycle.
JobHandler = Callable[[dict[str, Any] | None], Awaitable[dict[str, Any] | None]]


class _Registry:
    """Type-keyed handler registry. Created once at module import."""

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        """Register a handler for a job type. Overwrites silently — that
        matches the test pattern where suites re-register fakes."""
        self._handlers[job_type] = handler

    def get(self, job_type: str) -> JobHandler | None:
        return self._handlers.get(job_type)


_registry = _Registry()


def register_handler(job_type: str, handler: JobHandler) -> None:
    """Register ``handler`` as the executor for jobs of type ``job_type``.

    Job types are free-form strings the caller picks (``evaluation_run``,
    ``ingest_url``, …). The corresponding handler runs inside the API
    process; it can use any async primitives, including the database
    session helpers.
    """
    _registry.register(job_type, handler)


async def _run_job(job_id: int, job_type: str, payload: dict[str, Any] | None) -> None:
    """Internal: drive one job through its lifecycle.

    Always swallows exceptions — the executor must never propagate a
    handler failure into the asyncio task scheduler (where it would log
    as an unhandled exception). ``mark_failed`` captures the traceback.
    """
    handler = _registry.get(job_type)
    if handler is None:
        await mark_failed(job_id, f"No handler registered for job type {job_type!r}")
        logger.error("Job %d (%s): no handler registered", job_id, job_type)
        return

    try:
        await mark_running(job_id)
    except Exception:
        # If we can't even transition to running, the row is gone or the DB
        # is broken — there's nothing useful left to do. Log and bail.
        logger.exception("Job %d (%s): mark_running failed", job_id, job_type)
        return

    try:
        result = await handler(payload)
    except Exception as exc:  # noqa: BLE001 — boundary: capture every failure
        tb = "".join(traceback.format_exception(exc))
        # Keep the error message short for the admin Jobs table; the full
        # traceback is logged for forensic correlation.
        logger.exception("Job %d (%s) failed", job_id, job_type)
        await mark_failed(job_id, f"{type(exc).__name__}: {exc}\n\n{tb}"[:4000])
        return

    try:
        await mark_completed(job_id, result)
    except Exception:
        logger.exception("Job %d (%s): mark_completed failed", job_id, job_type)


async def enqueue(
    job_type: str,
    payload: dict[str, Any] | None = None,
) -> JobOut:
    """Create a job row and schedule its handler in the background.

    Returns the created row immediately (status ``queued``). The caller
    can hand the id off to a polling client; the admin Jobs page reads
    the same row.
    """
    job = await create_job(JobCreate(type=job_type, payload=payload))
    # asyncio.create_task ensures the coroutine runs on the running loop
    # but the awaiter doesn't block. The task reference is intentionally
    # not stored — the DB row IS the durable handle.
    asyncio.create_task(
        _run_job(job.id, job.type, payload), name=f"job-{job.id}-{job.type}"
    )
    return job


__all__ = ["JobHandler", "enqueue", "register_handler"]
