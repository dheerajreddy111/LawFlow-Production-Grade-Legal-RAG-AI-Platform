"""Async writer for evaluation-run history.

Persistence is best-effort — the evaluation result has already been
produced when we get here, and the user should never lose it because a
DB hiccup blocked the row write. Errors are logged and swallowed.
"""

from __future__ import annotations

import logging

from app.db.session import session_scope
from app.evaluation.metrics import EvaluationReport
from app.evaluation.models import EvaluationRun

logger = logging.getLogger(__name__)


async def record_evaluation_run(
    *,
    report: EvaluationReport,
    dataset_filename: str,
    name: str | None,
    created_by: int | None,
) -> int | None:
    """Persist one EvaluationRun. Returns the row id, or None on failure.

    Caller may discard the return value — the absence of an id is
    handled by logging only. Used by ``/api/v1/evaluation/run``.
    """
    try:
        async with session_scope() as session:
            run = EvaluationRun(
                name=(name or dataset_filename)[:200],
                dataset_filename=dataset_filename[:200],
                total_rows=int(report.summary.total_rows),
                scored_rows=int(report.summary.scored_rows),
                failed_rows=int(report.summary.failed_rows),
                f1_mean=float(report.summary.f1_score.mean),
                cosine_mean=float(report.summary.cosine_similarity.mean),
                keyword_mean=float(report.summary.keyword_overlap.mean),
                retrieval_mean=float(report.summary.retrieval_confidence.mean),
                created_by=created_by,
                report_json=report.model_dump_json(),
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            return int(run.id)
    except Exception:  # noqa: BLE001 — boundary: history writes are best-effort
        logger.exception("Failed to record evaluation run (history)")
        return None
