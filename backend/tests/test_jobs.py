"""Job lifecycle persistence tests.

These exercise the persistence helpers directly — no HTTP, no admin
UI. The model + helpers are the public surface for any future async
work that needs an observable row in the ``jobs`` table.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.session import create_all
from app.jobs import (
    JobCreate,
    JobStatus,
    create_job,
    mark_completed,
    mark_failed,
    mark_running,
)
from app.jobs.persistence import get_job, list_recent_jobs


def _run(coro):
    """Run an awaitable on a fresh loop — avoids fighting pytest-asyncio's loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _provision_schema() -> None:
    """The conftest fixture creates a fresh SQLite per test but doesn't run
    create_all (lifespan normally would). Provision the tables ourselves."""
    await create_all()


def test_create_job_starts_queued():
    async def run() -> None:
        await _provision_schema()
        job = await create_job(
            JobCreate(type="evaluation_run", payload={"file": "t.csv"})
        )
        assert job.id > 0
        assert job.status == JobStatus.QUEUED
        assert job.payload == {"file": "t.csv"}
        assert job.result is None
        assert job.error is None
        assert job.started_at is None
        assert job.completed_at is None

    _run(run())


def test_lifecycle_queued_to_completed():
    async def run() -> None:
        await _provision_schema()
        job = await create_job(JobCreate(type="evaluation_run"))
        running = await mark_running(job.id)
        assert running.status == JobStatus.RUNNING
        assert running.started_at is not None
        assert running.completed_at is None

        done = await mark_completed(job.id, {"rows_scored": 12})
        assert done.status == JobStatus.COMPLETED
        assert done.result == {"rows_scored": 12}
        assert done.error is None
        assert done.completed_at is not None
        assert done.started_at is not None

    _run(run())


def test_lifecycle_queued_to_failed():
    async def run() -> None:
        await _provision_schema()
        job = await create_job(JobCreate(type="ingest_url"))
        await mark_running(job.id)
        failed = await mark_failed(job.id, "TimeoutError: provider 30s")
        assert failed.status == JobStatus.FAILED
        assert failed.error == "TimeoutError: provider 30s"
        assert failed.result is None
        assert failed.completed_at is not None

    _run(run())


def test_mark_running_unknown_id_raises():
    async def run() -> None:
        await _provision_schema()
        with pytest.raises(LookupError):
            await mark_running(9999)

    _run(run())


def test_payload_round_trips_through_json():
    """Persisted payload survives create → read with the same structure."""
    async def run() -> None:
        await _provision_schema()
        payload = {"sources": ["a", "b"], "options": {"force": True, "count": 3}}
        job = await create_job(JobCreate(type="reprocess", payload=payload))
        again = await get_job(job.id)
        assert again is not None
        assert again.payload == payload

    _run(run())


def test_list_recent_jobs_returns_newest_first():
    async def run() -> None:
        await _provision_schema()
        first = await create_job(JobCreate(type="a"))
        second = await create_job(JobCreate(type="b"))
        third = await create_job(JobCreate(type="c"))
        rows = await list_recent_jobs(limit=10)
        ids = [r.id for r in rows]
        assert ids[:3] == [third.id, second.id, first.id]

    _run(run())


def test_job_status_is_terminal_invariant():
    assert JobStatus.COMPLETED.is_terminal is True
    assert JobStatus.FAILED.is_terminal is True
    assert JobStatus.QUEUED.is_terminal is False
    assert JobStatus.RUNNING.is_terminal is False
