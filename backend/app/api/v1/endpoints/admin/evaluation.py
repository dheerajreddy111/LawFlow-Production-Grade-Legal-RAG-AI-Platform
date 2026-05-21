"""Admin endpoints for the persistent evaluation run history.

- ``GET    /evaluation/runs``             recent-first list of runs
- ``GET    /evaluation/runs/{run_id}``    single run with full per-row report
- ``DELETE /evaluation/runs/{run_id}``    remove a persisted run

The runs themselves are produced by ``POST /api/v1/evaluation/run`` —
that endpoint writes into ``evaluation_runs`` via the persistence
helper. These admin routes are read/manage-only.
"""

from __future__ import annotations

import json as _json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import User, require_admin
from app.db.session import get_session
from app.utils.time import iso_utc

router = APIRouter()


# ── Response shapes ─────────────────────────────────────────────────────────


class EvaluationRunSummary(BaseModel):
    """One row in the evaluation history table."""

    id: int
    name: str
    dataset_filename: str
    total_rows: int
    scored_rows: int
    failed_rows: int
    f1_mean: float
    cosine_mean: float
    keyword_mean: float
    retrieval_mean: float
    created_by: int | None = None
    created_at: str  # ISO-8601


class EvaluationRunsListResponse(BaseModel):
    runs: list[EvaluationRunSummary]
    total: int
    # Cursor pagination: when `next_cursor` is set, the caller can pass it
    # back as the `cursor` query parameter to fetch the next page. `null`
    # signals "no more rows". See list_evaluation_runs for the contract.
    next_cursor: int | None = None


class EvaluationRunDetail(EvaluationRunSummary):
    """Detail view — augments the summary with the persisted report JSON."""

    # Full EvaluationReport (parsed) — shape matches
    # app.evaluation.metrics.EvaluationReport.
    report: dict[str, Any]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _run_to_summary(run: Any) -> EvaluationRunSummary:
    return EvaluationRunSummary(
        id=int(run.id),
        name=run.name or run.dataset_filename,
        dataset_filename=run.dataset_filename,
        total_rows=int(run.total_rows),
        scored_rows=int(run.scored_rows),
        failed_rows=int(run.failed_rows),
        f1_mean=float(run.f1_mean),
        cosine_mean=float(run.cosine_mean),
        keyword_mean=float(run.keyword_mean),
        retrieval_mean=float(run.retrieval_mean),
        created_by=run.created_by,
        created_at=iso_utc(run.created_at),
    )


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get(
    "/evaluation/runs",
    response_model=EvaluationRunsListResponse,
    summary="Past evaluation runs, most recent first (cursor-paginated)",
)
async def list_evaluation_runs(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Cap on the number of rows returned"),
    ] = 50,
    cursor: Annotated[
        int | None,
        Query(
            ge=1,
            description=(
                "ID-based cursor — pass the previous response's "
                "`next_cursor` to fetch the next page. Omit for the first page."
            ),
        ),
    ] = None,
) -> EvaluationRunsListResponse:
    """List evaluation runs, newest first.

    Pagination uses an ID cursor (cheap, monotonic, immune to the same
    ``created_at`` collisions that can break offset pagination on
    SQLite). The response includes ``next_cursor`` when more rows exist;
    a ``null`` ``next_cursor`` means the caller has reached the end.
    """
    from app.evaluation.models import EvaluationRun

    stmt = select(EvaluationRun).order_by(EvaluationRun.id.desc())
    if cursor is not None:
        stmt = stmt.where(EvaluationRun.id < cursor)
    # Fetch one extra row so we can decide whether more pages exist
    # without a second COUNT(*). Strip the sentinel before serialising.
    stmt = stmt.limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    summaries = [_run_to_summary(r) for r in rows]
    next_cursor = int(rows[-1].id) if has_more and rows else None
    return EvaluationRunsListResponse(
        runs=summaries, total=len(summaries), next_cursor=next_cursor
    )


@router.get(
    "/evaluation/runs/{run_id}",
    response_model=EvaluationRunDetail,
    summary="Single evaluation run with full per-row report",
)
async def get_evaluation_run(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    run_id: Annotated[int, Path(description="Evaluation run id", ge=1)],
) -> EvaluationRunDetail:
    from app.evaluation.models import EvaluationRun

    run = await session.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation run {run_id} not found",
        )

    try:
        report = _json.loads(run.report_json) if run.report_json else {}
    except Exception:  # noqa: BLE001 — defensive: malformed JSON shouldn't 500
        report = {}

    summary = _run_to_summary(run)
    return EvaluationRunDetail(**summary.model_dump(), report=report)


@router.delete(
    "/evaluation/runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one evaluation run",
)
async def delete_evaluation_run(
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
    run_id: Annotated[int, Path(description="Evaluation run id", ge=1)],
) -> None:
    from app.evaluation.models import EvaluationRun

    run = await session.get(EvaluationRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Evaluation run {run_id} not found",
        )
    await session.delete(run)
    await session.commit()
