"""Retention sweeps for high-volume tables.

Three tables grow append-only:

  - ``query_events``     analytics log — bounded by retention window.
  - ``evaluation_runs``  benchmark history — bounded by retention window.
  - ``jobs``             background-job rows — bounded by retention window
                         AND a stale-running reaper that flags
                         jobs left in ``running`` past a wall-clock
                         threshold as ``failed`` (the API process most
                         likely crashed mid-job).

All three are *opt-in* via environment variables (default values are
generous enough to be inoffensive even on small databases — see
:func:`_settings_from_env`). When disabled (set the window to 0) the
sweep is a no-op.

Configuration (env)
-------------------
  - ``RETENTION_QUERY_EVENTS_DAYS``     default 90  (set to 0 to disable)
  - ``RETENTION_EVAL_RUNS_DAYS``        default 180
  - ``RETENTION_JOBS_DAYS``             default 30
  - ``STALE_JOB_RUNNING_HOURS``         default 2   (running > N hours → failed)
  - ``RETENTION_SWEEP_INTERVAL_HOURS``  default 24  (how often to sweep)

The retention loop runs as a long-lived asyncio task started in the
FastAPI lifespan (see :mod:`app.main`). It sleeps for the configured
interval between sweeps. Each sweep is wrapped in a broad except so a
DB hiccup never tears the loop down.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update

from app.analytics.models import QueryEvent
from app.db.session import session_scope
from app.evaluation.models import EvaluationRun
from app.jobs.models import Job
from app.jobs.types import JobStatus

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _settings_from_env() -> dict[str, int]:
    """Snapshot retention knobs from the environment.

    Re-read every sweep so an operator can tune via SIGHUP-style env
    refresh without restarting the API. Cheap (a handful of os.getenv).
    """
    return {
        "query_events_days": _int_env("RETENTION_QUERY_EVENTS_DAYS", 90),
        "eval_runs_days": _int_env("RETENTION_EVAL_RUNS_DAYS", 180),
        "jobs_days": _int_env("RETENTION_JOBS_DAYS", 30),
        "stale_running_hours": _int_env("STALE_JOB_RUNNING_HOURS", 2),
    }


# ── Per-table sweeps ──────────────────────────────────────────────────────


async def prune_query_events(days: int) -> int:
    """Drop ``query_events`` rows older than ``days`` days.

    Returns the number of rows deleted. ``days <= 0`` disables.
    """
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with session_scope() as session:
        stmt = delete(QueryEvent).where(QueryEvent.created_at < cutoff)
        result = await session.execute(stmt)
        await session.commit()
        deleted = result.rowcount or 0
    if deleted:
        logger.info("Retention: pruned %d query_events rows older than %d days", deleted, days)
    return int(deleted)


async def prune_evaluation_runs(days: int) -> int:
    """Drop ``evaluation_runs`` rows older than ``days`` days."""
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with session_scope() as session:
        stmt = delete(EvaluationRun).where(EvaluationRun.created_at < cutoff)
        result = await session.execute(stmt)
        await session.commit()
        deleted = result.rowcount or 0
    if deleted:
        logger.info("Retention: pruned %d evaluation_runs rows older than %d days", deleted, days)
    return int(deleted)


async def prune_jobs(days: int) -> int:
    """Drop terminal jobs older than ``days`` days. Non-terminal rows are
    left alone — those go through ``reap_stale_jobs`` instead."""
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    async with session_scope() as session:
        stmt = delete(Job).where(
            Job.completed_at.is_not(None),
            Job.completed_at < cutoff,
        )
        result = await session.execute(stmt)
        await session.commit()
        deleted = result.rowcount or 0
    if deleted:
        logger.info("Retention: pruned %d job rows older than %d days", deleted, days)
    return int(deleted)


async def reap_stale_jobs(hours: int) -> int:
    """Flag jobs stuck in ``running`` past ``hours`` as ``failed``.

    These come from API processes that crashed mid-handler. The row is
    still there; the executor that owned it isn't. Mark with a clear
    diagnostic so an operator can correlate with logs.
    """
    if hours <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with session_scope() as session:
        stmt = (
            update(Job)
            .where(Job.status == JobStatus.RUNNING.value)
            .where(Job.started_at.is_not(None))
            .where(Job.started_at < cutoff)
            .values(
                status=JobStatus.FAILED.value,
                error=f"Reaped: stuck in running state past {hours}h cutoff",
                completed_at=datetime.now(timezone.utc),
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        reaped = result.rowcount or 0
    if reaped:
        logger.warning("Retention: reaped %d stuck-running jobs (> %dh)", reaped, hours)
    return int(reaped)


# ── Orchestration ─────────────────────────────────────────────────────────


async def run_retention_sweep() -> dict[str, int]:
    """Run every sweep once. Returns per-table deletion counts.

    Each step is independently try/excepted so a single failing sweep
    doesn't sabotage the rest. The aggregated result is logged for
    forensic recovery.
    """
    cfg = _settings_from_env()
    counts: dict[str, int] = {}
    for label, coro in (
        ("query_events", prune_query_events(cfg["query_events_days"])),
        ("evaluation_runs", prune_evaluation_runs(cfg["eval_runs_days"])),
        ("jobs", prune_jobs(cfg["jobs_days"])),
        ("stale_jobs", reap_stale_jobs(cfg["stale_running_hours"])),
    ):
        try:
            counts[label] = await coro
        except Exception:  # noqa: BLE001 — boundary: continue with other sweeps
            logger.exception("Retention sweep step %s failed", label)
            counts[label] = -1
    logger.info("Retention sweep complete: %s", counts)
    return counts


def start_retention_loop() -> asyncio.Task | None:
    """Spawn the periodic-sweep task on the current event loop.

    Returns the Task so callers (the lifespan) can cancel it on shutdown.
    Returns ``None`` if the loop is disabled (sweep interval ≤ 0).

    The interval is read once at start; restart the process to change it.
    Individual retention windows are re-read on every sweep — see
    :func:`_settings_from_env`.
    """
    interval_hours = _int_env("RETENTION_SWEEP_INTERVAL_HOURS", 24)
    if interval_hours <= 0:
        logger.info("Retention sweep disabled (interval=%d)", interval_hours)
        return None
    interval_s = interval_hours * 3600

    async def loop() -> None:
        logger.info("Retention sweep loop started (interval=%dh)", interval_hours)
        # Stagger the first run a few seconds in so the API has finished
        # its other startup work before we hit the DB.
        try:
            await asyncio.sleep(5)
            while True:
                try:
                    await run_retention_sweep()
                except Exception:  # noqa: BLE001 — boundary
                    logger.exception("Retention sweep raised")
                await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            logger.info("Retention sweep loop cancelled")
            raise

    return asyncio.create_task(loop(), name="retention-sweep")


__all__ = [
    "prune_evaluation_runs",
    "prune_jobs",
    "prune_query_events",
    "reap_stale_jobs",
    "run_retention_sweep",
    "start_retention_loop",
]
