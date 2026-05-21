"""GET /api/v1/admin/overview — headline KPIs for the dashboard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import User, require_admin
from app.auth.models import User as UserModel
from app.db.session import get_session
from app.rag.vector_store import vector_store
from app.services.metrics import metrics

router = APIRouter()


# ── Response shapes ─────────────────────────────────────────────────────────


class DocumentsSummary(BaseModel):
    total: int  # distinct source documents in the vector store
    chunks_total: int  # total chunks (across all versions)
    chunks_active: int  # chunks not marked superseded


class QueriesSummary(BaseModel):
    total: int
    by_route: dict[str, int]
    # ``route_share`` is by_route normalised to a 0..1 fraction so the UI can
    # render percentages without a second division.
    route_share: dict[str, float]


class LatencySummary(BaseModel):
    count: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float


class IngestionSummary(BaseModel):
    by_extension: dict[str, int]
    total: int


class UsersSummary(BaseModel):
    total: int
    active: int
    admins: int


class OverviewResponse(BaseModel):
    documents: DocumentsSummary
    queries: QueriesSummary
    latency: LatencySummary
    ingestion: IngestionSummary
    users: UsersSummary
    uptime_seconds: float


# ── Builders ────────────────────────────────────────────────────────────────


def _build_queries_summary(snap: dict) -> QueriesSummary:
    counters = snap.get("counters") or {}
    total = int(counters.get("queries_total", 0))
    by_route: dict[str, int] = {}
    for name, val in counters.items():
        if not name.startswith("queries_by_route."):
            continue
        # name format: "queries_by_route.route=deterministic"
        suffix = name[len("queries_by_route.") :]
        if "=" not in suffix:
            continue
        _, route = suffix.split("=", 1)
        by_route[route] = int(val)
    denominator = sum(by_route.values()) or 1
    route_share = {k: round(v / denominator, 4) for k, v in by_route.items()}
    return QueriesSummary(total=total, by_route=by_route, route_share=route_share)


def _build_latency_summary(snap: dict) -> LatencySummary:
    h = (snap.get("histograms") or {}).get("process_query_ms") or {}
    return LatencySummary(
        count=int(h.get("count", 0)),
        mean_ms=round(float(h.get("mean", 0.0)), 2),
        p50_ms=round(float(h.get("p50", 0.0)), 2),
        p95_ms=round(float(h.get("p95", 0.0)), 2),
        p99_ms=round(float(h.get("p99", 0.0)), 2),
    )


def _build_ingestion_summary(snap: dict) -> IngestionSummary:
    counters = snap.get("counters") or {}
    by_ext: dict[str, int] = {}
    for name, val in counters.items():
        if not name.startswith("ingest_total."):
            continue
        suffix = name[len("ingest_total.") :]
        if "=" not in suffix:
            continue
        _, ext = suffix.split("=", 1)
        by_ext[ext] = int(val)
    return IngestionSummary(by_extension=by_ext, total=sum(by_ext.values()))


async def _build_documents_summary() -> DocumentsSummary:
    sources = await vector_store.list_sources_summary()
    chunks_total = sum(int(s.get("chunks_total", 0)) for s in sources)
    chunks_active = sum(int(s.get("chunks_active", 0)) for s in sources)
    return DocumentsSummary(
        total=len(sources),
        chunks_total=chunks_total,
        chunks_active=chunks_active,
    )


async def _build_users_summary(session: AsyncSession) -> UsersSummary:
    total = await session.scalar(select(func.count()).select_from(UserModel)) or 0
    active = (
        await session.scalar(
            select(func.count())
            .select_from(UserModel)
            .where(UserModel.is_active.is_(True))
        )
        or 0
    )
    admins = (
        await session.scalar(
            select(func.count())
            .select_from(UserModel)
            .where(UserModel.role == "admin")
            .where(UserModel.is_active.is_(True))
        )
        or 0
    )
    return UsersSummary(total=int(total), active=int(active), admins=int(admins))


# ── Route ───────────────────────────────────────────────────────────────────


@router.get(
    "/overview",
    response_model=OverviewResponse,
    summary="Headline metrics for the admin dashboard Overview page",
)
async def overview(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OverviewResponse:
    snap = metrics.snapshot()
    documents = await _build_documents_summary()
    users = await _build_users_summary(session)
    return OverviewResponse(
        documents=documents,
        queries=_build_queries_summary(snap),
        latency=_build_latency_summary(snap),
        ingestion=_build_ingestion_summary(snap),
        users=users,
        uptime_seconds=float(snap.get("uptime_seconds", 0.0)),
    )
