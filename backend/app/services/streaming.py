"""
Server-Sent Events (SSE) streaming infrastructure for LawFlow.

This adds token-by-token streaming *on top of* the existing orchestration
(`LegalService.process_query`) without modifying it.  The synchronous
pipeline result is decomposed into an SSE stream:

    event: meta    → query, intent, route, confidence, reason, entities,
                      statute_sections   (everything the UI needs up-front)
    event: token   → one answer chunk    (repeated, in order)
    event: done    → terminal success marker
    event: error   → graceful failure    (terminal; never a raw 500)

Token chunking is whitespace-preserving so the client can append deltas
verbatim.  When real RAG/LLM generation is wired in, genuine token deltas
can flow through this same protocol with zero client changes — only the
producer passed to :func:`query_event_stream` changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.integrations.lc import set_run_metadata, set_run_outputs, traced

logger = logging.getLogger(__name__)

# One "token" ≈ a word plus its trailing whitespace. Keeps the stream
# readable and lets the client concatenate chunks without reflow logic.
_TOKEN_RE = re.compile(r"\S+\s*")

# Delay between chunks — perceptible streaming without being sluggish.
_TOKEN_DELAY_S = 0.012

ProcessFn = Callable[[str], Awaitable[dict[str, Any]]]


def format_sse(event: str, data: Any) -> str:
    """Render one SSE frame. Data is JSON-encoded on a single line."""
    payload = json.dumps(jsonable_encoder(data), ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    return _TOKEN_RE.findall(text) or [text]


async def query_event_stream(
    query: str,
    process: ProcessFn,
) -> AsyncGenerator[str, None]:
    """Yield SSE frames for one legal query.

    ``process`` is the *untouched* ``LegalService.process_query`` coroutine —
    orchestration is reused, not rewritten.  Any failure is surfaced as a
    terminal ``error`` event so the connection closes cleanly rather than
    emitting a mid-stream HTTP 500.

    Observability: emits ``set_run_metadata`` for the streaming lifecycle
    (event counts, terminal state) on the ambient LangSmith span when one
    is active. The orchestration span itself is opened by the decorated
    ``LegalService.process_query`` so per-stage timings remain accurate.
    """
    # Mark the streaming lifecycle on the ambient trace (no-op when off).
    set_run_metadata(streaming=True, query_chars=len(query or ""))
    try:
        result = await process(query)
    except Exception as exc:  # noqa: BLE001 — boundary: must not leak a 500
        logger.exception("Query processing failed during stream")
        set_run_outputs(stream_state="error", error=str(exc))
        yield format_sse("error", {"message": f"Failed to process query: {exc}"})
        return

    yield format_sse(
        "meta",
        {
            "query": result.get("query", query),
            "intent": result.get("intent"),
            "route": result.get("route"),
            "confidence": result.get("confidence"),
            "reason": result.get("reason"),
            "entities": result.get("entities", []),
            "statute_sections": result.get("statute_sections", []),
            "domain": result.get("domain"),
            "related_acts": result.get("related_acts", []),
            "suggestions": result.get("suggestions", []),
            # Enhanced right-rail context (optional → ignored by older clients).
            "help_text": result.get("help_text"),
            "next_actions": result.get("next_actions", []),
            "examples": result.get("examples", []),
            # Per-chunk retrieval explainability — populated on RAG-routed
            # queries only; older clients ignore the field. See
            # app/services/legal_service.py::_chunk_to_record for the shape.
            "retrieved_chunks": result.get("retrieved_chunks", []),
        },
    )

    tokens_emitted = 0
    try:
        for token in _tokenize(result.get("answer", "")):
            yield format_sse("token", {"text": token})
            tokens_emitted += 1
            await asyncio.sleep(_TOKEN_DELAY_S)
    except asyncio.CancelledError:
        # Client disconnected — let the cancellation propagate so the
        # server can tear the generator down cleanly.
        logger.info("SSE stream cancelled by client")
        set_run_outputs(
            stream_state="cancelled", tokens_emitted=tokens_emitted
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Streaming interrupted")
        set_run_outputs(
            stream_state="error",
            tokens_emitted=tokens_emitted,
            error=str(exc),
        )
        yield format_sse("error", {"message": f"Streaming interrupted: {exc}"})
        return

    set_run_outputs(stream_state="done", tokens_emitted=tokens_emitted)
    yield format_sse("done", {})
