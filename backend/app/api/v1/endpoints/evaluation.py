"""
POST /api/v1/evaluation/run — evaluate the LawFlow pipeline against a CSV
test set.

Request:  multipart/form-data
          - ``file``   UTF-8 CSV whose header contains at least
                       ``question`` and ``expected_answer``.
          - ``name``   optional run label (≤200 chars); defaults to the
                       uploaded filename.

Response: an EvaluationReport — aggregated metric summary plus per-row
          breakdown.

Side-effect: each successful run is persisted to ``evaluation_runs`` so
the admin history page can render it. Persistence failure is logged but
never overrides the actual report — the user still gets their result.
"""

import base64
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.auth import User, require_admin
from app.evaluation.metrics import EvaluationReport
from app.evaluation.persistence import record_evaluation_run
from app.evaluation.service import EvaluationService, InvalidDatasetError
from app.jobs.executor import enqueue
from app.jobs.handlers import JOB_TYPE_EVALUATION_RUN
from app.jobs.schemas import JobOut

router = APIRouter()
_service = EvaluationService()


@router.post(
    "/run",
    response_model=EvaluationReport,
    summary="Run a CSV test set through LawFlow and score it",
)
async def run_evaluation(
    admin: Annotated[User, Depends(require_admin)],
    file: UploadFile = File(
        ..., description="UTF-8 CSV with `question` and `expected_answer` columns"
    ),
    name: Annotated[
        str | None,
        Form(description="Optional human label for this run (defaults to filename)"),
    ] = None,
) -> EvaluationReport:
    raw = await file.read()
    filename = file.filename or "dataset.csv"
    try:
        report = await _service.evaluate(filename, raw)
    except InvalidDatasetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Persist for the admin history view. Best-effort: the user still
    # receives the report even if storage fails.
    await record_evaluation_run(
        report=report,
        dataset_filename=filename,
        name=name,
        created_by=admin.id,
    )
    return report


class AsyncRunResponse(BaseModel):
    """Wire shape for the async-run kick-off — small, polling-friendly."""

    job: JobOut


@router.post(
    "/run-async",
    response_model=AsyncRunResponse,
    status_code=202,
    summary="Queue a CSV evaluation as a background job; returns the job id",
)
async def run_evaluation_async(
    admin: Annotated[User, Depends(require_admin)],
    file: UploadFile = File(
        ..., description="UTF-8 CSV with `question` and `expected_answer` columns"
    ),
    name: Annotated[
        str | None,
        Form(description="Optional human label for this run (defaults to filename)"),
    ] = None,
) -> AsyncRunResponse:
    """Background-job variant of ``POST /evaluation/run``.

    A long benchmark (several hundred rows × LLM round-trips) easily
    exceeds the proxy's HTTP idle timeout. This endpoint returns
    immediately with a job id; the caller polls ``GET /api/v1/jobs/{id}``
    until ``status`` is terminal. The actual work is run by the
    ``evaluation_run`` handler — see :mod:`app.jobs.handlers`.

    The CSV is base64-encoded into the payload so the job table (and the
    admin UI) can render the job without holding a file handle, and so
    the executor can recover the exact bytes that were submitted.
    """
    raw = await file.read()
    filename = file.filename or "dataset.csv"
    if not raw:
        raise HTTPException(status_code=400, detail="Empty CSV")
    payload = {
        "filename": filename,
        "csv_b64": base64.b64encode(raw).decode("ascii"),
        "name": name,
        "created_by": admin.id,
    }
    job = await enqueue(JOB_TYPE_EVALUATION_RUN, payload=payload)
    return AsyncRunResponse(job=job)
