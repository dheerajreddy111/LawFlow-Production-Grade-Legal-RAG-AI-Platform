"""
POST /api/v1/query  — classify intent and extract entities from a legal query.

Request:
    {"query": "What does Section 25F of the Industrial Disputes Act say?"}

Response:
    {
      "query": "What does Section 25F …",
      "intent": "bare_act_query",
      "confidence": 0.89,
      "entities": [
        {"type": "SECTION", "value": "Section 25F", "confidence": 0.93, "start": 11, "end": 22},
        {"type": "ACT",     "value": "Industrial Disputes Act", "confidence": 0.90, "start": 26, "end": 50}
      ]
    }
"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.analytics import record_query_event
from app.auth import User, current_user
from app.entities.extractor import LegalEntity
from app.services.legal_service import LegalService
from app.services.statute_service import SectionResult
from app.services.streaming import query_event_stream

router = APIRouter()
_service = LegalService()


def _scoped_session(user: User, session_id: str | None) -> str | None:
    """Namespace memory by user so cross-user history can't leak."""
    if session_id is None:
        return None
    return f"u{user.id}:{session_id}"


async def _record(
    *,
    user: User,
    session_id: str | None,
    query: str,
    result: dict,
    latency_ms: float,
    has_error: bool = False,
    error_reason: str | None = None,
) -> None:
    """Persist a row in query_events. Best-effort; never raises."""
    await record_query_event(
        user_id=user.id,
        session_id=session_id,
        query=query,
        intent=str(result.get("intent") or "unknown"),
        route=str(result.get("route") or "unknown"),
        confidence=float(result.get("confidence") or 0.0),
        latency_ms=latency_ms,
        has_error=has_error,
        domain=result.get("domain"),
        error_reason=error_reason,
    )


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(
        default=None, description="Opaque client session id for multi-turn memory"
    )


class RetrievedChunkRecord(BaseModel):
    """One retrieved-and-reranked chunk surfaced for explainability.

    Populated on the RAG path only; deterministic queries do not run
    vector retrieval so the list is empty. The full set of stage
    scores is optional — older ingestion paths surface only the
    `similarity` + `rerank_score` pair, while the hybrid retrieval
    pipeline fills in the BM25, fusion, and cross-encoder fields.
    """

    source: str
    similarity: float
    rerank_score: float | None = None
    rerank_reason: str | None = None
    section: str = ""
    act: str = ""
    excerpt: str = ""
    # Retrieval-stage diagnostics — see app/rag/retrieval.py.
    vector_score: float | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    fused_score: float | None = None
    fused_rank: int | None = None
    cross_encoder_score: float | None = None


class QueryResponse(BaseModel):
    query:            str
    answer:           str
    intent:           str
    confidence:       float
    entities:         list[LegalEntity]
    route:            str
    reason:           str
    statute_sections: list[SectionResult] = []
    # Additive context for the dynamic right rail (optional → schema preserved).
    domain:           str | None = None
    related_acts:     list[str] = []
    suggestions:      list[str] = []
    # Enhanced right-rail context — all optional so older clients are
    # unaffected. Populated only on legal routes (deterministic / rag).
    help_text:        str | None = None
    next_actions:     list[str] = []
    examples:         list[str] = []
    # Per-chunk retrieval explainability (RAG path only).
    retrieved_chunks: list[RetrievedChunkRecord] = []


@router.post("", response_model=QueryResponse, summary="Classify and extract from a legal query")
async def analyse_query(
    body: QueryRequest,
    user: Annotated[User, Depends(current_user)],
) -> QueryResponse:
    scoped = _scoped_session(user, body.session_id)
    start = time.perf_counter()
    try:
        result = await _service.process_query(body.query, scoped)
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        await _record(
            user=user,
            session_id=body.session_id,
            query=body.query,
            result={"intent": "unknown", "route": "unknown"},
            latency_ms=latency_ms,
            has_error=True,
            error_reason=f"{type(exc).__name__}: {exc}",
        )
        raise

    latency_ms = (time.perf_counter() - start) * 1000.0
    await _record(
        user=user,
        session_id=body.session_id,
        query=body.query,
        result=result,
        latency_ms=latency_ms,
    )
    return QueryResponse(**result)


@router.post(
    "/stream",
    summary="Stream a legal query response token-by-token (SSE)",
    response_class=StreamingResponse,
)
async def analyse_query_stream(
    body: QueryRequest,
    user: Annotated[User, Depends(current_user)],
) -> StreamingResponse:
    """SSE variant of POST /api/v1/query.

    Reuses the existing orchestration unchanged; emits a `meta` event with
    intent/route/confidence/entities/sections, then `token` events, then
    `done` (or a terminal `error`).

    Analytics: the SSE handler can't easily measure end-to-end latency
    from the route (the streamer owns the lifecycle), so we record an
    event right after the orchestration's classify-and-resolve step
    finishes, before token streaming begins. Generation latency is
    already captured in metrics' ``generation_ms`` histogram.
    """
    scoped = _scoped_session(user, body.session_id)

    async def _process(q: str) -> dict:
        start = time.perf_counter()
        try:
            result = await _service.process_query(q, scoped)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            await _record(
                user=user,
                session_id=body.session_id,
                query=q,
                result={"intent": "unknown", "route": "unknown"},
                latency_ms=latency_ms,
                has_error=True,
                error_reason=f"{type(exc).__name__}: {exc}",
            )
            raise
        latency_ms = (time.perf_counter() - start) * 1000.0
        await _record(
            user=user,
            session_id=body.session_id,
            query=q,
            result=result,
            latency_ms=latency_ms,
        )
        return result

    return StreamingResponse(
        query_event_stream(body.query, _process),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering
        },
    )
