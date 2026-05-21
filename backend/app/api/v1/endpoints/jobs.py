"""Jobs admin API.

- ``GET /api/v1/jobs``              recent-first list of jobs (admin)
- ``GET /api/v1/jobs/{job_id}``     single job with payload + result (admin)

Read-only — write paths live next to the work they describe (e.g.
``POST /api/v1/evaluation/run-async`` for evaluation runs). The shapes
mirror :class:`app.jobs.JobOut` so admin UIs can render directly.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel

from app.auth import User, require_admin
from app.jobs.persistence import get_job, list_recent_jobs
from app.jobs.schemas import JobOut

router = APIRouter()


class JobListResponse(BaseModel):
    jobs: list[JobOut]
    total: int


@router.get(
    "",
    response_model=JobListResponse,
    summary="List recent background jobs (most recent first)",
)
async def list_jobs(
    _admin: Annotated[User, Depends(require_admin)],
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Cap on the number of rows returned"),
    ] = 50,
) -> JobListResponse:
    rows = await list_recent_jobs(limit=limit)
    return JobListResponse(jobs=rows, total=len(rows))


@router.get(
    "/{job_id}",
    response_model=JobOut,
    summary="Single background job — payload + result + error",
)
async def get_one_job(
    _admin: Annotated[User, Depends(require_admin)],
    job_id: Annotated[int, Path(description="Job id", ge=1)],
) -> JobOut:
    row = await get_job(job_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )
    return row
