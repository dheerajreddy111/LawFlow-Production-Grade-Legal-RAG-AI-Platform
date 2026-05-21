"""Cross-encoder reranker for the LawFlow RAG pipeline.

The bi-encoder (``BAAI/bge-small-en-v1.5``) embeds queries and chunks
independently and compares via cosine — fast, but symmetric retrieval
patterns produce flat top-k scores for nearly-identical passages. A
cross-encoder takes ``(query, chunk)`` as a single input and computes
a query-conditional relevance score, which is what we actually want
for the final reordering before passing context to the LLM.

This module is **opt-in** via env (``CROSS_ENCODER_ENABLED=true``) and
**lazy-loaded** on first use so the warm-up cost is amortised over the
session rather than added to every cold start. When disabled (the
default), the pipeline falls through to the existing deterministic
reranker unchanged.

Why ``BAAI/bge-reranker-base`` by default
-----------------------------------------
- ~280 MB model — runs comfortably on CPU at sub-150ms per (query, 10
  chunks) batch.
- Trained against the same BGE-family bi-encoder, so the lexical
  features it learned to amplify are the same ones the retrieval
  upstream already foregrounds.
- Apache 2.0 license — fine for a production deployment.

The model is overridable via ``CROSS_ENCODER_MODEL``; popular drop-ins
include ``cross-encoder/ms-marco-MiniLM-L-6-v2`` (faster, slightly
weaker) and ``cross-encoder/ms-marco-MiniLM-L-12-v2``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import TYPE_CHECKING, Any

from app.integrations.lc import set_run_outputs, traced

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


# ── Configuration ───────────────────────────────────────────────────────────


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


CROSS_ENCODER_ENABLED: bool = _env_bool("CROSS_ENCODER_ENABLED", False)
CROSS_ENCODER_MODEL: str = os.getenv(
    "CROSS_ENCODER_MODEL", "BAAI/bge-reranker-base"
)
# Hard cap on the number of (query, chunk) pairs we'll score per call.
# Cross-encoders are quadratic-ish in batch tokens; 32 keeps a query
# under 200ms on CPU for the 800-char chunks the chunker produces.
CROSS_ENCODER_MAX_PAIRS: int = int(os.getenv("CROSS_ENCODER_MAX_PAIRS", "32"))


# ── Singleton model holder ──────────────────────────────────────────────────


class _CrossEncoderHolder:
    """Lazy singleton so the model is only loaded if we actually use it."""

    def __init__(self) -> None:
        self._model: "CrossEncoder | None" = None
        self._lock = threading.Lock()

    def get(self) -> "CrossEncoder":
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import CrossEncoder

                    logger.info(
                        "Loading cross-encoder reranker: %s",
                        CROSS_ENCODER_MODEL,
                    )
                    # CPU inference is fine for our scale. The model picks
                    # up a GPU automatically if torch sees one.
                    self._model = CrossEncoder(CROSS_ENCODER_MODEL)
        return self._model


_HOLDER = _CrossEncoderHolder()


def is_enabled() -> bool:
    """True when the env flag is on and the model can be loaded.

    Reads the env var dynamically so test suites can flip it mid-run.
    Use this guard in callers to skip the import + load in the disabled
    case.
    """
    return _env_bool("CROSS_ENCODER_ENABLED", CROSS_ENCODER_ENABLED)


# ── Public surface ──────────────────────────────────────────────────────────


@traced(name="rerank.cross_encoder", run_type="tool")
async def rerank_with_cross_encoder(
    query: str,
    chunks: list[Any],
    *,
    text_attr: str = "text",
    top_k: int | None = None,
) -> list[tuple[Any, float]]:
    """Score ``(query, chunk.text)`` pairs and return chunks in best-first order.

    Returns ``[(chunk, score), ...]`` so the caller can decide whether
    to drop low-score chunks or just reorder. ``score`` is the raw
    cross-encoder logit — higher == more relevant. When the encoder is
    disabled, returns the input list unchanged (scores set to 0.0).

    ``text_attr`` allows the caller to pass any chunk-shaped object
    (``RetrievedChunk``, ``FusedHit``, ``Document``) without translation.
    """
    if not chunks:
        set_run_outputs(n_pairs=0, n_scored=0, enabled=is_enabled())
        return []
    if not query or not query.strip():
        set_run_outputs(n_pairs=len(chunks), n_scored=0, enabled=False)
        return [(c, 0.0) for c in chunks]
    if not is_enabled():
        set_run_outputs(n_pairs=len(chunks), n_scored=0, enabled=False)
        return [(c, 0.0) for c in chunks]

    # Bound the batch — cross-encoders scale poorly past ~32 pairs on CPU.
    if len(chunks) > CROSS_ENCODER_MAX_PAIRS:
        # Score the head; pass the tail through with score 0 so the
        # caller can still order them after the scored block.
        head = chunks[:CROSS_ENCODER_MAX_PAIRS]
        tail = chunks[CROSS_ENCODER_MAX_PAIRS:]
        scored_head = await _score(query, head, text_attr)
        ordered = sorted(scored_head, key=lambda pair: pair[1], reverse=True)
        ordered.extend((c, 0.0) for c in tail)
        set_run_outputs(
            n_pairs=len(chunks),
            n_scored=len(head),
            n_truncated=len(tail),
            enabled=True,
            model=CROSS_ENCODER_MODEL,
        )
        return ordered[: top_k] if top_k else ordered

    scored = await _score(query, chunks, text_attr)
    ordered = sorted(scored, key=lambda pair: pair[1], reverse=True)
    set_run_outputs(
        n_pairs=len(chunks),
        n_scored=len(chunks),
        enabled=True,
        model=CROSS_ENCODER_MODEL,
    )
    return ordered[: top_k] if top_k else ordered


async def _score(
    query: str, chunks: list[Any], text_attr: str
) -> list[tuple[Any, float]]:
    """Compute cross-encoder scores for one batch. Off the event loop."""
    pairs: list[tuple[str, str]] = []
    for c in chunks:
        text = getattr(c, text_attr, None)
        if text is None and isinstance(c, dict):
            text = c.get(text_attr, "")
        pairs.append((query, text or ""))

    # Lazy import keeps the dep cost out of the disabled path.
    from app.services.metrics import metrics

    async with metrics.timer("rag_cross_encoder_ms"):
        scores = await asyncio.to_thread(_predict_sync, pairs)
    return list(zip(chunks, scores))


def _predict_sync(pairs: list[tuple[str, str]]) -> list[float]:
    """Blocking cross-encoder forward pass. Always called from a worker thread."""
    model = _HOLDER.get()
    raw = model.predict(pairs, show_progress_bar=False)
    # CrossEncoder.predict returns a numpy float array. Coerce defensively
    # so the caller never sees a numpy type bleeding into the wire layer.
    return [float(x) for x in raw]


__all__ = [
    "CROSS_ENCODER_ENABLED",
    "CROSS_ENCODER_MODEL",
    "is_enabled",
    "rerank_with_cross_encoder",
]
