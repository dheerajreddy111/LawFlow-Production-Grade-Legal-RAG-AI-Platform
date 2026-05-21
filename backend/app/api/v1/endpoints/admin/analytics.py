"""GET /api/v1/admin/analytics — query volume, intent + route distribution.

Aggregates the persistent ``query_events`` log over a selected time
window (1h / 24h / 7d / 30d).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import User, require_admin
from app.db.session import get_session

router = APIRouter()


# ── Response shapes ─────────────────────────────────────────────────────────


class AnalyticsTotals(BaseModel):
    total: int
    errors: int
    error_rate: float
    avg_latency_ms: float
    window_start: str  # ISO-8601 UTC


class IntentCount(BaseModel):
    intent: str
    count: int


class FailureEntry(BaseModel):
    ts: str
    query: str
    intent: str
    route: str
    error_reason: str | None = None


class AnalyticsResponse(BaseModel):
    range: str
    routes: list[str]
    # Each timeline row is {ts: iso, <route1>: int, <route2>: int, ...}.
    # We keep it un-modelled so adding new routes never breaks the
    # response schema — purely additive.
    timeseries: list[dict[str, Any]]
    intent_distribution: list[IntentCount]
    route_share: dict[str, int]
    totals: AnalyticsTotals
    recent_failures: list[FailureEntry]


# ── Route ───────────────────────────────────────────────────────────────────


_ALLOWED_RANGES: tuple[str, ...] = ("1h", "24h", "7d", "30d")


@router.get(
    "/analytics",
    response_model=AnalyticsResponse,
    summary="Query analytics — volume, intent + route distribution, failures",
)
async def analytics(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    range_key: Annotated[
        str,
        Query(
            alias="range",
            description="Time window to aggregate over.",
            pattern="^(1h|24h|7d|30d)$",
        ),
    ] = "24h",
) -> AnalyticsResponse:
    # Belt-and-braces: pattern above already rejects bad input with 422,
    # but if a caller bypasses the validator we still raise cleanly.
    if range_key not in _ALLOWED_RANGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"range must be one of {', '.join(_ALLOWED_RANGES)}",
        )

    from app.analytics import queries as q

    routes, timeseries = await q.volume_by_route(session, range_key=range_key)  # type: ignore[arg-type]
    intent_counts = await q.intent_distribution(session, range_key=range_key)  # type: ignore[arg-type]
    share = await q.route_share(session, range_key=range_key)  # type: ignore[arg-type]
    totals = await q.overall_totals(session, range_key=range_key)  # type: ignore[arg-type]
    failures = await q.recent_failures(session, limit=10)

    return AnalyticsResponse(
        range=range_key,
        routes=routes,
        timeseries=timeseries,
        intent_distribution=[IntentCount(**r) for r in intent_counts],
        route_share=share,
        totals=AnalyticsTotals(**totals),
        recent_failures=[FailureEntry(**f) for f in failures],
    )
