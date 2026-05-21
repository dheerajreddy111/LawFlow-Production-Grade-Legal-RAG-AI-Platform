"""Background-executor regressions.

Exercise the lifecycle plumbing without touching the live HTTP API:

  - A successful handler transitions queued → running → completed.
  - A raising handler transitions queued → running → failed and the
    error message lands on the row.
  - Unknown job types fail fast with a clear message.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.session import create_all
from app.jobs.executor import enqueue, register_handler
from app.jobs.persistence import get_job
from app.jobs.types import JobStatus


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _wait_for_terminal(job_id: int, timeout: float = 5.0):
    """Poll the row until status is terminal or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        job = await get_job(job_id)
        assert job is not None
        if job.status.is_terminal:
            return job
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"Job {job_id} stuck at {job.status}")
        await asyncio.sleep(0.05)


def test_executor_runs_handler_and_marks_completed():
    async def run() -> None:
        await create_all()
        register_handler(
            "test_ok",
            lambda payload: _async_return({"echo": payload["x"] * 2}),
        )
        job = await enqueue("test_ok", payload={"x": 21})
        assert job.status == JobStatus.QUEUED
        final = await _wait_for_terminal(job.id)
        assert final.status == JobStatus.COMPLETED
        assert final.result == {"echo": 42}
        assert final.error is None
        assert final.started_at is not None
        assert final.completed_at is not None

    _run(run())


def test_executor_marks_failed_on_handler_exception():
    async def run() -> None:
        await create_all()

        async def boom(_payload: dict | None) -> dict:
            raise RuntimeError("simulated failure")

        register_handler("test_fail", boom)
        job = await enqueue("test_fail", payload={"n": 1})
        final = await _wait_for_terminal(job.id)
        assert final.status == JobStatus.FAILED
        assert final.error is not None
        assert "simulated failure" in final.error
        # Result must NOT be set on failure.
        assert final.result is None

    _run(run())


def test_executor_fails_unknown_job_type():
    async def run() -> None:
        await create_all()
        job = await enqueue("does-not-exist")
        final = await _wait_for_terminal(job.id)
        assert final.status == JobStatus.FAILED
        assert "No handler registered" in (final.error or "")

    _run(run())


# Helper — register_handler expects an async callable, so wrap a result.
async def _async_return(value):
    return value
