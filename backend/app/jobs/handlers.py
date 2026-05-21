"""Job handlers — concrete async tasks the executor can run.

Each handler is a thin wrapper around an existing service: the heavy
lifting still lives in :mod:`app.evaluation` / :mod:`app.ingestion`.
This module is the bridge between the executor's payload-in /
result-out contract and the service-level functions.

Importing this module registers every handler in
:mod:`app.jobs.executor`'s registry. That registration is idempotent
so the import can be repeated safely (test suites do this).
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from app.evaluation.metrics import EvaluationReport
from app.evaluation.persistence import record_evaluation_run
from app.evaluation.service import EvaluationService, InvalidDatasetError
from app.jobs.executor import register_handler

logger = logging.getLogger(__name__)

# Job type tokens — exposed so the API endpoints + admin UI can refer to
# the same string without typos.
JOB_TYPE_EVALUATION_RUN = "evaluation_run"


_evaluation_service = EvaluationService()


async def _run_evaluation(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Run a CSV through the evaluation pipeline and persist the report.

    Payload shape:
        - ``filename`` (str)             dataset filename (operator-facing label).
        - ``csv_b64`` (str)              base64-encoded UTF-8 CSV bytes.
        - ``name`` (str, optional)       operator-facing run label.
        - ``created_by`` (int, optional) user id of the admin who fired it.

    Result shape:
        - ``run_id`` (int | None)        DB id of the persisted run; ``None``
                                         if persistence failed (the report
                                         was still produced).
        - ``summary`` (dict)             EvaluationReport.summary as JSON.
        - ``scored_rows`` (int)
        - ``failed_rows`` (int)
    """
    if not payload:
        raise ValueError("evaluation_run payload is required")

    filename = str(payload.get("filename") or "dataset.csv")
    csv_b64 = payload.get("csv_b64")
    if not isinstance(csv_b64, str) or not csv_b64:
        raise ValueError("evaluation_run payload must include csv_b64 (base64 string)")

    try:
        raw = base64.b64decode(csv_b64)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError(f"csv_b64 is not valid base64: {exc}") from exc

    try:
        report: EvaluationReport = await _evaluation_service.evaluate(filename, raw)
    except InvalidDatasetError as exc:
        # InvalidDatasetError is a *user error* (bad CSV) — re-raise as
        # ValueError so the executor records it as a clear failure
        # message rather than an opaque stack trace.
        raise ValueError(str(exc)) from exc

    name = payload.get("name")
    created_by = payload.get("created_by")
    run_id = await record_evaluation_run(
        report=report,
        dataset_filename=filename,
        name=name if isinstance(name, str) else None,
        created_by=created_by if isinstance(created_by, int) else None,
    )

    summary = report.summary.model_dump()
    return {
        "run_id": run_id,
        "summary": summary,
        "scored_rows": summary["scored_rows"],
        "failed_rows": summary["failed_rows"],
        "total_rows": summary["total_rows"],
    }


register_handler(JOB_TYPE_EVALUATION_RUN, _run_evaluation)


__all__ = ["JOB_TYPE_EVALUATION_RUN"]
