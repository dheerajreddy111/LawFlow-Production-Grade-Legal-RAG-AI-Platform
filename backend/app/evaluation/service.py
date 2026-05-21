"""
EvaluationService — runs a CSV test set through the LawFlow pipeline and
scores generated answers against expected answers.

Pipeline (per row)
-------------------
    1. Run `question` through LegalService.process_query (existing
       orchestration, reused unchanged).
    2. Capture the generated `answer` and the retrieval/route `confidence`.
    3. Score generated vs expected: token F1, keyword overlap, and
       embedding cosine similarity (BAAI/bge-small-en-v1.5).

Rows are processed concurrently (bounded) and embedded in a single batch
for throughput. A row that raises is captured as a failed RowResult rather
than aborting the run — partial results are still useful for a dashboard.

`retrieval_confidence` is the pipeline's reported confidence. Today that is
the classifier/route confidence from process_query; when RAG generation is
wired in it becomes RAGResponse.confidence with no schema change here.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
from dataclasses import dataclass

from app.evaluation.metrics import (
    EvaluationReport,
    RowResult,
    aggregate,
    cosine_similarity,
    keyword_overlap,
    token_f1,
)
from app.evaluation.normalize import normalize_for_eval
from app.integrations.lc import set_run_metadata, set_run_outputs, traced
from app.rag.embeddings import embedding_service
from app.services.legal_service import LegalService

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = ("question", "expected_answer")
_MAX_CONCURRENCY = 8


class InvalidDatasetError(ValueError):
    """Raised when the uploaded CSV is malformed or missing columns."""


def parse_dataset(raw: bytes) -> list[tuple[str, str]]:
    """Parse CSV bytes into [(question, expected_answer), ...].

    Raises InvalidDatasetError on decode failure, missing columns, or an
    empty dataset.
    """
    try:
        text = raw.decode("utf-8-sig")  # tolerate a BOM from Excel exports
    except UnicodeDecodeError as exc:
        raise InvalidDatasetError("CSV must be UTF-8 encoded.") from exc

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise InvalidDatasetError("CSV is empty.")

    headers = {h.strip().lower() for h in reader.fieldnames if h}
    missing = [c for c in _REQUIRED_COLUMNS if c not in headers]
    if missing:
        raise InvalidDatasetError(
            f"CSV is missing required column(s): {', '.join(missing)}. "
            f"Expected headers: {', '.join(_REQUIRED_COLUMNS)}."
        )

    rows: list[tuple[str, str]] = []
    for raw_row in reader:
        norm = {
            (k.strip().lower() if k else ""): (v or "").strip()
            for k, v in raw_row.items()
        }
        question = norm.get("question", "")
        expected = norm.get("expected_answer", "")
        if question:  # skip blank lines / trailing commas
            rows.append((question, expected))

    if not rows:
        raise InvalidDatasetError("CSV contains no usable rows.")
    return rows


@dataclass
class _RowRun:
    """Outcome of running one question through the pipeline."""

    generated: str = ""
    intent: str = ""
    route: str = ""
    confidence: float = 0.0
    error: str | None = None


class EvaluationService:
    def __init__(self, legal_service: LegalService | None = None) -> None:
        self._legal = legal_service or LegalService()
        self._sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def _run_one(self, question: str) -> _RowRun:
        """Run one question through the pipeline. Never raises.

        ``evaluation_mode=True`` is the central reason this method
        exists separately from the chat path: it flips the prompt +
        composer to the terse benchmark variant, so token-overlap
        metrics measure content rather than the production-grade
        markdown wrapper. Chat / API consumers never set this flag.
        """
        async with self._sem:
            try:
                result = await self._legal.process_query(
                    question, evaluation_mode=True
                )
                return _RowRun(
                    generated=result.get("answer", ""),
                    intent=str(result.get("intent") or ""),
                    route=str(result.get("route") or ""),
                    confidence=float(result.get("confidence") or 0.0),
                )
            except Exception as exc:  # noqa: BLE001 — per-row isolation
                logger.exception("Evaluation row failed: %s", question[:80])
                return _RowRun(error=str(exc))

    @traced(name="evaluation.run", run_type="chain")
    async def evaluate(
        self, dataset_name: str, raw_csv: bytes
    ) -> EvaluationReport:
        pairs = parse_dataset(raw_csv)
        # Tag the parent span so LangSmith dashboards can filter by
        # dataset and reason about row counts. The CSV bytes themselves
        # are NEVER attached — they may contain client-confidential
        # questions; only counts + the operator-supplied dataset name
        # cross the wire.
        set_run_metadata(
            dataset_name=dataset_name,
            n_rows=len(pairs),
            evaluation_mode=True,
        )

        # 1–2. Run every question through the pipeline (bounded concurrency).
        runs: list[_RowRun] = await asyncio.gather(
            *(self._run_one(q) for q, _ in pairs)
        )

        # Batch-embed expected + generated for cosine similarity. Only
        # successful rows are embedded; failures get cosine 0.0.
        embed_index: list[int] = []
        to_embed: list[str] = []
        for i, run in enumerate(runs):
            if run.error is None:
                embed_index.append(i)
                to_embed.append(pairs[i][1])      # expected
                to_embed.append(run.generated)    # generated

        vectors: list[list[float]] = []
        if to_embed:
            vectors = await embedding_service.embed_batch(
                to_embed, is_query=False
            )

        cosine_by_row: dict[int, float] = {}
        for slot, row_i in enumerate(embed_index):
            exp_vec = vectors[2 * slot]
            gen_vec = vectors[2 * slot + 1]
            cosine_by_row[row_i] = cosine_similarity(exp_vec, gen_vec)

        # 3. Score every row.
        results: list[RowResult] = []
        for i, (q, expected) in enumerate(pairs):
            run = runs[i]
            if run.error is not None:
                results.append(
                    RowResult(
                        question=q,
                        expected_answer=expected,
                        generated_answer="",
                        f1_score=0.0,
                        cosine_similarity=0.0,
                        keyword_overlap=0.0,
                        retrieval_confidence=0.0,
                        error=run.error,
                    )
                )
                continue

            # Symmetric normalisation — both sides receive the same
            # treatment so the comparison stays fair. We do this here
            # rather than inside ``token_f1`` so the row's stored
            # answer text remains the raw model output (the admin UI
            # shows the literal answer for forensics). Embedding-side
            # cosine is computed against the raw text already because
            # the embedding model handles case + punctuation cleanly
            # itself; we don't want to strip semantic markers there.
            norm_gen = normalize_for_eval(run.generated)
            norm_exp = normalize_for_eval(expected)
            results.append(
                RowResult(
                    question=q,
                    expected_answer=expected,
                    generated_answer=run.generated,
                    f1_score=token_f1(norm_gen, norm_exp),
                    cosine_similarity=cosine_by_row.get(i, 0.0),
                    keyword_overlap=keyword_overlap(norm_gen, norm_exp),
                    retrieval_confidence=round(run.confidence, 4),
                    intent=run.intent or None,
                    route=run.route or None,
                )
            )

        report = EvaluationReport(
            summary=aggregate(dataset_name, results),
            results=results,
        )
        # Surface aggregate metrics on the parent span so a glance at the
        # LangSmith UI shows the run's outcome without re-opening the
        # report blob. Individual per-row text is intentionally absent —
        # the per-row spans nested under this one already carry the
        # question via their own metadata.
        s = report.summary
        set_run_outputs(
            n_rows=s.total_rows,
            n_scored=s.scored_rows,
            n_failed=s.failed_rows,
            f1_mean=s.f1_score.mean,
            cosine_mean=s.cosine_similarity.mean,
            keyword_mean=s.keyword_overlap.mean,
            retrieval_mean=s.retrieval_confidence.mean,
        )
        return report
