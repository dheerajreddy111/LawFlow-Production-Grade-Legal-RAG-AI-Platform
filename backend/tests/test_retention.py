"""Retention sweep regressions.

The retention module is responsible for keeping append-only tables
bounded. We test each table-level prune in isolation against a fresh
SQLite DB to ensure:

  - Old rows are deleted.
  - Fresh rows survive.
  - A retention window of 0 short-circuits without touching the DB.
  - The stale-job reaper transitions running rows past the cutoff to
    failed and leaves recent runs alone.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import create_all, session_scope
from app.jobs.cleanup import (
    prune_evaluation_runs,
    prune_jobs,
    prune_query_events,
    reap_stale_jobs,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_prune_query_events_deletes_old_rows_only():
    async def run() -> None:
        from app.analytics.models import QueryEvent

        await create_all()
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=120)
        recent = now - timedelta(days=10)
        async with session_scope() as session:
            session.add_all(
                [
                    QueryEvent(intent="x", route="r", confidence=0.0, latency_ms=0.0, has_error=False, query_preview="a", created_at=old),
                    QueryEvent(intent="x", route="r", confidence=0.0, latency_ms=0.0, has_error=False, query_preview="b", created_at=recent),
                ]
            )
            await session.commit()

        deleted = await prune_query_events(90)
        assert deleted == 1

        # Fresh row survives.
        async with session_scope() as session:
            from sqlalchemy import func, select

            count = await session.scalar(select(func.count()).select_from(QueryEvent))
            assert int(count or 0) == 1

    _run(run())


def test_prune_query_events_disabled_when_days_zero():
    async def run() -> None:
        from app.analytics.models import QueryEvent

        await create_all()
        old = datetime.now(timezone.utc) - timedelta(days=400)
        async with session_scope() as session:
            session.add(QueryEvent(intent="x", route="r", confidence=0.0, latency_ms=0.0, has_error=False, query_preview="z", created_at=old))
            await session.commit()

        deleted = await prune_query_events(0)
        assert deleted == 0
        # And it remains.
        from sqlalchemy import func, select

        async with session_scope() as session:
            count = await session.scalar(select(func.count()).select_from(QueryEvent))
            assert int(count or 0) == 1

    _run(run())


def test_prune_evaluation_runs_deletes_old():
    async def run() -> None:
        from app.evaluation.models import EvaluationRun

        await create_all()
        now = datetime.now(timezone.utc)
        async with session_scope() as session:
            session.add_all(
                [
                    EvaluationRun(name="old", dataset_filename="x.csv", total_rows=1, scored_rows=1, failed_rows=0, f1_mean=0.5, cosine_mean=0.5, keyword_mean=0.5, retrieval_mean=0.5, created_at=now - timedelta(days=400), report_json="{}"),
                    EvaluationRun(name="new", dataset_filename="y.csv", total_rows=1, scored_rows=1, failed_rows=0, f1_mean=0.5, cosine_mean=0.5, keyword_mean=0.5, retrieval_mean=0.5, created_at=now - timedelta(days=5), report_json="{}"),
                ]
            )
            await session.commit()

        deleted = await prune_evaluation_runs(180)
        assert deleted == 1

    _run(run())


def test_prune_jobs_only_terminal_old_rows():
    async def run() -> None:
        from app.jobs.models import Job

        await create_all()
        now = datetime.now(timezone.utc)
        async with session_scope() as session:
            session.add_all(
                [
                    # Old + terminal → pruned
                    Job(type="x", status="completed", created_at=now - timedelta(days=100), completed_at=now - timedelta(days=99)),
                    # Old but never terminal → kept (the reaper handles those)
                    Job(type="x", status="running", created_at=now - timedelta(days=100), started_at=now - timedelta(days=100)),
                    # Recent terminal → kept
                    Job(type="x", status="completed", created_at=now - timedelta(days=2), completed_at=now - timedelta(days=2)),
                ]
            )
            await session.commit()

        deleted = await prune_jobs(30)
        assert deleted == 1

    _run(run())


def test_reap_stale_jobs_flags_long_running_failed():
    async def run() -> None:
        from app.jobs.models import Job

        await create_all()
        now = datetime.now(timezone.utc)
        async with session_scope() as session:
            session.add_all(
                [
                    Job(type="x", status="running", created_at=now - timedelta(hours=10), started_at=now - timedelta(hours=10)),
                    Job(type="x", status="running", created_at=now - timedelta(minutes=15), started_at=now - timedelta(minutes=15)),
                ]
            )
            await session.commit()

        reaped = await reap_stale_jobs(2)
        assert reaped == 1

        # Confirm the long-running row flipped to failed.
        from sqlalchemy import select

        async with session_scope() as session:
            rows = (await session.execute(select(Job).order_by(Job.id))).scalars().all()
            statuses = [r.status for r in rows]
            assert "failed" in statuses and "running" in statuses

    _run(run())
