"""Read-side aggregations powering /api/v1/admin/analytics.

Designed to run as plain SQL via SQLAlchemy. We keep the buckets
client-friendly: each row is ``{bucket_start_iso, route, count}`` so
the frontend can pivot into a stacked area chart without re-doing the
group-by in TypeScript.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.models import QueryEvent
from app.utils.time import as_utc

# Hourly granularity for short ranges, daily for week+; keeps the
# rendered chart legible without overloading the wire.
TimeRange = Literal["1h", "24h", "7d", "30d"]


@dataclass(frozen=True)
class RangeConfig:
    window: timedelta
    bucket: timedelta
    # SQL strftime format for SQLite; we map to ISO 8601 client-side.
    bucket_label: str


_RANGE_CONFIGS: dict[TimeRange, RangeConfig] = {
    "1h":  RangeConfig(timedelta(hours=1),   timedelta(minutes=5),  "5min"),
    "24h": RangeConfig(timedelta(hours=24),  timedelta(hours=1),    "hour"),
    "7d":  RangeConfig(timedelta(days=7),    timedelta(hours=6),    "6h"),
    "30d": RangeConfig(timedelta(days=30),   timedelta(days=1),     "day"),
}


def range_config(range_key: TimeRange) -> RangeConfig:
    return _RANGE_CONFIGS[range_key]


def _bucket_start(ts: datetime, bucket: timedelta) -> datetime:
    """Floor ``ts`` to the nearest bucket boundary (UTC, naive-safe)."""
    aware = as_utc(ts)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = aware - epoch
    seconds = int(delta.total_seconds())
    bucket_seconds = int(bucket.total_seconds()) or 1
    floored = (seconds // bucket_seconds) * bucket_seconds
    return epoch + timedelta(seconds=floored)


async def volume_by_route(
    session: AsyncSession, *, range_key: TimeRange
) -> tuple[list[str], list[dict]]:
    """Return (route_list, timeseries) for the requested window.

    ``timeseries`` rows look like ``{ts: iso8601, <route>: int, ...}``
    with one entry per bucket; every bucket carries every route name so
    the recharts stacked-area component can render without holes.
    """
    cfg = _RANGE_CONFIGS[range_key]
    now = datetime.now(timezone.utc)
    since = now - cfg.window

    stmt = (
        select(QueryEvent.route, QueryEvent.created_at)
        .where(QueryEvent.created_at >= since)
    )
    result = await session.execute(stmt)
    rows = list(result)

    routes: set[str] = set()
    bucketed: dict[datetime, dict[str, int]] = {}
    for route, ts in rows:
        route_str = str(route or "unknown")
        routes.add(route_str)
        bucket = _bucket_start(ts, cfg.bucket)
        slot = bucketed.setdefault(bucket, {})
        slot[route_str] = slot.get(route_str, 0) + 1

    # Build a dense timeline so chart renders even when some buckets are empty.
    timeline: list[dict] = []
    start = _bucket_start(since, cfg.bucket)
    cursor = start
    end = _bucket_start(now, cfg.bucket)
    route_list = sorted(routes)
    while cursor <= end:
        slot = bucketed.get(cursor, {})
        row = {"ts": cursor.isoformat()}
        for route in route_list:
            row[route] = slot.get(route, 0)
        timeline.append(row)
        cursor += cfg.bucket

    return route_list, timeline


async def intent_distribution(
    session: AsyncSession, *, range_key: TimeRange
) -> list[dict]:
    cfg = _RANGE_CONFIGS[range_key]
    since = datetime.now(timezone.utc) - cfg.window
    stmt = (
        select(QueryEvent.intent, func.count())
        .where(QueryEvent.created_at >= since)
        .group_by(QueryEvent.intent)
        .order_by(func.count().desc())
    )
    result = await session.execute(stmt)
    return [{"intent": str(intent), "count": int(count)} for intent, count in result]


async def route_share(
    session: AsyncSession, *, range_key: TimeRange
) -> dict[str, int]:
    cfg = _RANGE_CONFIGS[range_key]
    since = datetime.now(timezone.utc) - cfg.window
    stmt = (
        select(QueryEvent.route, func.count())
        .where(QueryEvent.created_at >= since)
        .group_by(QueryEvent.route)
    )
    result = await session.execute(stmt)
    return {str(route): int(count) for route, count in result}


async def recent_failures(
    session: AsyncSession, *, limit: int = 10
) -> list[dict]:
    """Most recent events flagged ``has_error=True``. Independent of range
    so the operator always sees the latest red flags."""
    stmt = (
        select(
            QueryEvent.created_at,
            QueryEvent.query_preview,
            QueryEvent.intent,
            QueryEvent.route,
            QueryEvent.error_reason,
        )
        .where(QueryEvent.has_error.is_(True))
        .order_by(QueryEvent.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    out: list[dict] = []
    for created_at, query_preview, intent, route, error_reason in result:
        out.append(
            {
                "ts": as_utc(created_at).isoformat(),
                "query": query_preview or "",
                "intent": str(intent or ""),
                "route": str(route or ""),
                "error_reason": error_reason,
            }
        )
    return out


async def overall_totals(
    session: AsyncSession, *, range_key: TimeRange
) -> dict:
    cfg = _RANGE_CONFIGS[range_key]
    since = datetime.now(timezone.utc) - cfg.window
    total_stmt = select(func.count()).select_from(QueryEvent).where(QueryEvent.created_at >= since)
    error_stmt = (
        select(func.count())
        .select_from(QueryEvent)
        .where(QueryEvent.created_at >= since)
        .where(QueryEvent.has_error.is_(True))
    )
    avg_latency_stmt = (
        select(func.avg(QueryEvent.latency_ms))
        .where(QueryEvent.created_at >= since)
    )
    total = int(await session.scalar(total_stmt) or 0)
    errors = int(await session.scalar(error_stmt) or 0)
    avg_latency = float(await session.scalar(avg_latency_stmt) or 0.0)
    return {
        "total": total,
        "errors": errors,
        "error_rate": (errors / total) if total else 0.0,
        "avg_latency_ms": round(avg_latency, 2),
        "window_start": since.isoformat(),
    }
