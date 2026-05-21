"""Hybrid retrieval — vector + BM25, fused via Reciprocal Rank Fusion.

The fusion layer sits between the raw retrievers (vector + BM25) and
the reranker. It exists so the engine can ask one question — "what
chunks are most relevant?" — and get back a single list with each
chunk's contributions surfaced for explainability.

Reciprocal Rank Fusion
----------------------
RRF [Cormack et al., 2009] is the simplest robust fusion technique:
each retriever contributes ``1 / (k + rank)`` to a chunk's score, where
``rank`` is the chunk's 1-indexed position in that retriever's results
and ``k`` is a smoothing constant (default 60 in the literature; we use
the same). The chunk's final score is the sum of all contributions.

Why RRF over score-blending:
- Robust to wildly different score scales (cosine in [0,1], BM25 raw in
  whatever range the corpus produces).
- No retraining when the corpus grows or the embedding model changes.
- Cheap to compute and trivial to explain — every contribution is a
  ``(retriever, rank)`` tuple.

Weighting
---------
The default RRF formula gives each retriever equal voice. We add a
configurable weight per retriever (default 1.0 each) so the engine can
nudge the balance — e.g. semantic-heavy for long legal-research
queries, lexical-heavy for "Section 25F"-style lookups. The weighting
is multiplicative on the contribution, not exponential, so a 2.0
weight means "this retriever's rank counts twice as much".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.rag.bm25 import BM25Hit
from app.rag.vector_store import SearchResult

logger = logging.getLogger(__name__)


# ── Tunables ─────────────────────────────────────────────────────────────────

# RRF smoothing constant. 60 is the canonical default and produces stable
# behaviour across rank distributions.
RRF_K: int = 60


# ── Public types ─────────────────────────────────────────────────────────────


@dataclass
class FusedHit:
    """One chunk's fused score plus contributing retriever stages.

    ``contributions`` is a dict of ``retriever → rank`` for each
    retriever that surfaced this chunk. The explainability panel
    renders this so operators see *why* a chunk ranked where it did
    ("ranked 2 by vector, 1 by BM25 → fused #1").
    """

    chunk_id: str
    text: str
    source: str
    metadata: dict[str, Any]
    score: float                                       # RRF score
    vector_score: float | None = None                  # cosine similarity (if vec hit)
    bm25_score: float | None = None                    # raw BM25 (if bm25 hit)
    contributions: dict[str, int] = field(default_factory=dict)  # retriever → rank


# ── Fusion ───────────────────────────────────────────────────────────────────


def reciprocal_rank_fusion(
    vector_hits: list[SearchResult],
    bm25_hits: list[BM25Hit],
    *,
    weights: dict[str, float] | None = None,
    k: int = RRF_K,
    top_k: int = 10,
) -> list[FusedHit]:
    """Merge vector and BM25 hits into a single RRF-ranked list.

    ``weights`` overrides the per-retriever weight (defaults to 1.0 for
    both). ``k`` is the RRF smoothing constant; the literature default
    is 60 and we expose it so a benchmark can sweep without code
    changes.

    Output is sorted by fused score descending, capped at ``top_k``.
    Chunks that appear in both rankings get the sum of their
    contributions — RRF's core property.
    """
    w_vec = float((weights or {}).get("vector", 1.0))
    w_bm = float((weights or {}).get("bm25", 1.0))

    # Key by chunk_id so duplicate chunks (same id in both retrievers)
    # fuse. We hold the first-seen text + metadata because they are
    # identical across the two retrievers — both retrieve from the same
    # Chroma chunks.
    bag: dict[str, FusedHit] = {}

    for rank, hit in enumerate(vector_hits, start=1):
        if not hit.chunk_id:
            continue
        contrib = w_vec * (1.0 / (k + rank))
        entry = bag.setdefault(
            hit.chunk_id,
            FusedHit(
                chunk_id=hit.chunk_id,
                text=hit.text,
                source=hit.source,
                metadata=dict(hit.metadata or {}),
                score=0.0,
            ),
        )
        entry.score += contrib
        entry.vector_score = float(hit.score)
        entry.contributions["vector"] = rank

    for rank, hit in enumerate(bm25_hits, start=1):
        if not hit.chunk_id:
            continue
        contrib = w_bm * (1.0 / (k + rank))
        entry = bag.setdefault(
            hit.chunk_id,
            FusedHit(
                chunk_id=hit.chunk_id,
                text=hit.text,
                source=hit.source,
                metadata=dict(hit.metadata or {}),
                score=0.0,
            ),
        )
        entry.score += contrib
        entry.bm25_score = float(hit.score)
        entry.contributions["bm25"] = rank

    fused = sorted(bag.values(), key=lambda f: f.score, reverse=True)
    return fused[:top_k]


# ── Multi-list RRF (used by multi-query retrieval) ───────────────────────────


def rrf_merge_lists(
    ranked_lists: list[list[Any]],
    *,
    id_key: str = "chunk_id",
    weights: list[float] | None = None,
    k: int = RRF_K,
    top_k: int = 10,
) -> list[Any]:
    """Generic RRF over a list of ranked lists keyed by ``id_key``.

    Used by the multi-query retriever to fuse several variant-driven
    ranked lists into one. Returns the *first-seen* object for each id
    so chunks are not duplicated.
    """
    if not ranked_lists:
        return []
    weights = weights or [1.0] * len(ranked_lists)
    if len(weights) != len(ranked_lists):
        raise ValueError("weights must match ranked_lists length")

    scores: dict[str, float] = {}
    first_seen: dict[str, Any] = {}
    for ranked, w in zip(ranked_lists, weights):
        for rank, item in enumerate(ranked, start=1):
            cid = getattr(item, id_key, None) or (
                item.get(id_key) if isinstance(item, dict) else None
            )
            if not cid:
                continue
            scores[cid] = scores.get(cid, 0.0) + w * (1.0 / (k + rank))
            first_seen.setdefault(cid, item)

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [first_seen[cid] for cid, _ in ordered[:top_k]]
