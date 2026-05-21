"""End-to-end retrieval orchestrator.

Single entry point — :func:`retrieve` — that runs the full optimised
pipeline:

::

    query
      │
      ├── rewrite + variants + act/section detection
      │     │
      │     ▼
      │   multi-query × { vector + BM25 } → RRF fusion
      │     │
      │     ▼
      │   metadata filter narrowing (when an act / section was cited)
      │
      ▼
    deterministic rerank (existing legal-signal rerank.py)
      │
      ▼
    cross-encoder rerank (optional; env-gated)
      │
      ▼
    deduplicate + diversify (MMR-lite over already-ordered hits)
      │
      ▼
    final top-k RetrievedChunk list

The orchestrator preserves the existing :class:`RetrievedChunk` shape
so :class:`RAGEngine`, the LangGraph nodes, and the explainability
panel are unchanged. Every retriever and reranker writes its rank into
``RetrievedChunk.metadata`` keys prefixed with ``_lf_`` so the
explainability payload can render them.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from app.integrations.lc import set_run_outputs, traced
from app.rag.bm25 import BM25Hit, bm25_index
from app.rag.cross_encoder import is_enabled as cross_encoder_enabled
from app.rag.cross_encoder import rerank_with_cross_encoder
from app.rag.hybrid import FusedHit, reciprocal_rank_fusion, rrf_merge_lists
from app.rag.query_rewrite import RewrittenQuery, build_metadata_filter, rewrite_query
from app.rag.rerank import RAG_RETRIEVE_K
from app.rag.rerank import rerank as deterministic_rerank
from app.rag.vector_store import SearchResult, VectorStore, vector_store

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────────────────────


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# How many chunks each retriever surfaces per query variant. Wider here
# than RAG_RETRIEVE_K so the fusion + rerank stages have material to
# work with — a top-12 from vector + top-12 from BM25 gives the
# deterministic reranker a strong shortlist.
RETRIEVE_PER_VARIANT: int = _int_env("RAG_RETRIEVE_PER_VARIANT", 12)
# Fused-list size we hand to the deterministic reranker.
FUSED_TOP_K: int = _int_env("RAG_FUSED_TOP_K", 16)
# Vector / BM25 weighting in the RRF fusion. Default 0.6 / 0.4 leans
# semantic but keeps lexical signal strong — section-number queries
# still get a fair shot.
W_VECTOR: float = _float_env("RAG_W_VECTOR", 0.6)
W_BM25: float = _float_env("RAG_W_BM25", 0.4)
# MMR-lite penalty for chunks that share source + section number with
# an already-selected chunk.
DEDUP_PENALTY: float = _float_env("RAG_DEDUP_PENALTY", 0.85)

# How many representative chunks to pull when ``overview_mode=True`` and
# an act_key is resolved. We want enough breadth that the generator can
# list the major areas an Act covers, but not so many that the LLM gets
# overwhelmed; 12 sits comfortably below typical context windows even
# for terse models.
OVERVIEW_SAMPLE_SIZE: int = _int_env("RAG_OVERVIEW_SAMPLE_SIZE", 12)


# ── Internal types ──────────────────────────────────────────────────────────


@dataclass
class _Retrieved:
    """Hybrid-retrieved chunk with every stage's score attached.

    Kept separate from :class:`app.rag.engine.RetrievedChunk` so the
    orchestrator can carry all of the rich scoring through the
    pipeline; the final translation to ``RetrievedChunk`` happens at
    the exit.
    """

    chunk_id: str
    text: str
    source: str
    metadata: dict[str, Any]
    # Stage scores (any may be None).
    vector_score: float | None = None
    vector_rank: int | None = None
    bm25_score: float | None = None
    bm25_rank: int | None = None
    fused_score: float | None = None
    fused_rank: int | None = None
    rerank_score: float | None = None
    rerank_reason: str | None = None
    cross_encoder_score: float | None = None


# ── Public surface ──────────────────────────────────────────────────────────


@dataclass
class RetrievalResult:
    """Outcome of the orchestrator. ``chunks`` is best-first."""

    chunks: list[Any]                                  # list[RetrievedChunk]
    rewrite: RewrittenQuery
    timings_ms: dict[str, float]


@traced(name="rag.retrieve.hybrid", run_type="retriever")
async def retrieve(
    query: str,
    *,
    top_k: int = RAG_RETRIEVE_K,
    store: VectorStore = vector_store,
    jurisdiction: str | None = None,
    use_metadata_filter: bool = True,
    use_multi_query: bool = True,
    use_cross_encoder: bool | None = None,
    overview_mode: bool = False,
) -> RetrievalResult:
    """Run the full hybrid retrieval pipeline against the legal corpus.

    Parameters
    ----------
    query
        The user's question (or any retrieval target).
    top_k
        Final number of chunks returned. The pipeline runs with a wider
        fused window upstream and trims after rerank.
    store
        VectorStore to query (default: process-wide singleton).
    jurisdiction
        Optional jurisdiction filter (``extra.jurisdiction`` metadata).
    use_metadata_filter
        When True (default), narrow the search to acts the rewriter
        detected. Disable for benchmark sweeps that need to compare
        with/without filtering.
    use_multi_query
        When True (default), expand into variants and fuse.
    use_cross_encoder
        Override the env-driven flag. ``None`` defers to
        :func:`app.rag.cross_encoder.is_enabled`.
    overview_mode
        When True AND the rewriter resolved at least one act key, swap
        the hybrid pipeline for a diversified act-wide sample so the
        LLM can write a grounded summary of the act rather than a
        narrow section lookup. When no act resolves, falls back to
        normal hybrid retrieval — overview-mode is a hint, not a
        guarantee, so dispatch stays safe on ambiguous queries.
    """
    from app.rag.engine import RetrievedChunk  # local: avoid import cycle

    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    rewrite = rewrite_query(query)
    timings["rewrite_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    if not rewrite.original:
        return RetrievalResult(chunks=[], rewrite=rewrite, timings_ms=timings)

    # ── Overview branch: diversified act-wide sample ───────────────────────
    #
    # When the caller asked for overview mode AND we resolved an act, skip
    # the hybrid pipeline entirely and pull a representative slice of
    # chunks from that act. The hybrid path is built to surface a
    # *targeted* answer to a specific question; overview wants *breadth*
    # — definitions, headline provisions, penalty sections — so the
    # generator can list "what the act covers". Vector / BM25 / rerank
    # don't help here and actively hurt diversity by clustering on the
    # query terms.
    if overview_mode:
        if not rewrite.act_keys:
            # Overview asked for an Act we couldn't resolve. Bail
            # cleanly with zero chunks — the caller's no-provision
            # fallback emits the corpus-availability message rather
            # than dragging the user through hybrid retrieval and a
            # confused answer.
            set_run_outputs(
                n_returned=0,
                act_keys=[],
                overview_mode=True,
                overview_unresolved=True,
            )
            try:
                from app.services.metrics import metrics

                metrics.inc("rag_overview_unresolved_total")
            except Exception:  # noqa: BLE001
                pass
            return RetrievalResult(chunks=[], rewrite=rewrite, timings_ms=timings)
        t_overview = time.perf_counter()
        out = await _overview_sample(
            rewrite.act_keys,
            store=store,
            top_k=max(top_k, OVERVIEW_SAMPLE_SIZE),
        )
        timings["overview_ms"] = round(
            (time.perf_counter() - t_overview) * 1000, 2
        )
        set_run_outputs(
            n_returned=len(out),
            act_keys=rewrite.act_keys,
            overview_mode=True,
        )
        try:
            from app.services.metrics import metrics

            metrics.inc("rag_overview_queries_total")
            if not out:
                # ``act_keys`` resolved but the index has zero chunks
                # for them — drift between ACT_REGISTRY and Chroma.
                # Worth surfacing so the operator can re-ingest.
                metrics.inc("rag_overview_missing_act_total")
        except Exception:  # noqa: BLE001
            pass
        return RetrievalResult(chunks=out, rewrite=rewrite, timings_ms=timings)

    variants = rewrite.variants if use_multi_query else [rewrite.original]
    metadata_filter = (
        build_metadata_filter(
            rewrite.act_keys, jurisdiction=jurisdiction
        )
        if use_metadata_filter
        else (
            build_metadata_filter([], jurisdiction=jurisdiction)
        )
    )

    # ── Stage 1: multi-query × hybrid retrieval (vector + BM25) ─────────────
    t_stage = time.perf_counter()
    per_variant_fused: list[list[FusedHit]] = []
    for v in variants:
        vec_hits = await store.similarity_search(
            v, top_k=RETRIEVE_PER_VARIANT, where=metadata_filter
        )
        bm_hits = await bm25_index().search(v, top_k=RETRIEVE_PER_VARIANT, store=store)
        # If a metadata filter was applied, restrict BM25 to chunks that
        # match the same act_keys — BM25 doesn't know about Chroma's
        # filter and would otherwise leak out-of-scope hits.
        if metadata_filter and bm_hits:
            bm_hits = _apply_act_filter(bm_hits, rewrite.act_keys)
        fused = reciprocal_rank_fusion(
            vec_hits, bm_hits,
            weights={"vector": W_VECTOR, "bm25": W_BM25},
            top_k=FUSED_TOP_K,
        )
        per_variant_fused.append(fused)

    # Fuse the per-variant lists. With a single variant the call is a
    # straight passthrough (it is its own ranked list).
    if len(per_variant_fused) > 1:
        fused_hits: list[FusedHit] = rrf_merge_lists(
            per_variant_fused,
            id_key="chunk_id",
            top_k=FUSED_TOP_K,
        )
    else:
        fused_hits = per_variant_fused[0] if per_variant_fused else []
    timings["hybrid_ms"] = round((time.perf_counter() - t_stage) * 1000, 2)

    if not fused_hits:
        return RetrievalResult(chunks=[], rewrite=rewrite, timings_ms=timings)

    # Lift fused hits into the working type so we can carry every stage's
    # rank forward.
    retrieved: list[_Retrieved] = []
    for i, fh in enumerate(fused_hits, start=1):
        retrieved.append(
            _Retrieved(
                chunk_id=fh.chunk_id,
                text=fh.text,
                source=fh.source,
                metadata=fh.metadata,
                vector_score=fh.vector_score,
                vector_rank=fh.contributions.get("vector"),
                bm25_score=fh.bm25_score,
                bm25_rank=fh.contributions.get("bm25"),
                fused_score=fh.score,
                fused_rank=i,
            )
        )

    # ── Stage 2: deterministic rerank (existing legal-signal pass) ─────────
    t_stage = time.perf_counter()
    # The deterministic reranker operates on RetrievedChunk-shaped
    # objects. We translate, rerank, then copy the scores back.
    chunks_for_rerank = [
        RetrievedChunk(
            text=r.text,
            source=r.source,
            # Use fused score so primary-signal selection sees the union
            # ranking, not just vector similarity.
            score=r.vector_score if r.vector_score is not None else 0.0,
            metadata=r.metadata,
        )
        for r in retrieved
    ]
    reranked = deterministic_rerank(rewrite.original, chunks_for_rerank)
    # Map back by index — deterministic_rerank preserves the chunk
    # objects we gave it, so a simple identity match works.
    chunk_to_r: dict[int, _Retrieved] = {
        id(chunks_for_rerank[i]): retrieved[i] for i in range(len(retrieved))
    }
    kept: list[_Retrieved] = []
    for c in reranked:
        r = chunk_to_r.get(id(c))
        if r is None:
            continue
        r.rerank_score = c.rerank_score
        r.rerank_reason = c.rerank_reason
        kept.append(r)
    # If the legal-signal rerank dropped everything except the primary
    # (its design), use that one — but keep the fused-list tail as
    # backup for the cross-encoder so the LLM still sees diversity.
    if len(kept) < min(top_k, len(retrieved)):
        seen_ids = {r.chunk_id for r in kept}
        for r in retrieved:
            if r.chunk_id not in seen_ids:
                kept.append(r)
                if len(kept) >= top_k * 2:
                    break
    timings["rerank_ms"] = round((time.perf_counter() - t_stage) * 1000, 2)

    # ── Stage 3: cross-encoder rerank (optional, env-gated) ────────────────
    enable_ce = (
        use_cross_encoder if use_cross_encoder is not None else cross_encoder_enabled()
    )
    if enable_ce and kept:
        t_stage = time.perf_counter()
        scored = await rerank_with_cross_encoder(
            rewrite.original,
            kept,
            text_attr="text",
        )
        # `scored` is [(retrieved, score), ...]; rewrite the order and
        # stash the score for explainability.
        kept = []
        for r, s in scored:
            r.cross_encoder_score = float(s)
            kept.append(r)
        timings["cross_encoder_ms"] = round(
            (time.perf_counter() - t_stage) * 1000, 2
        )

    # ── Stage 4: dedup + diversity (MMR-lite) ──────────────────────────────
    t_stage = time.perf_counter()
    kept = _diversify(kept, k=top_k)
    timings["dedup_ms"] = round((time.perf_counter() - t_stage) * 1000, 2)

    # ── Translate back to RetrievedChunk for the engine ────────────────────
    out: list[RetrievedChunk] = []
    for r in kept[:top_k]:
        meta = dict(r.metadata)
        # Persist stage diagnostics under the _lf_ prefix so the
        # existing explainability layer can render them. The LLM
        # prompt assembly ignores anything in metadata, so this is
        # safe.
        meta["_lf_vector_rank"] = r.vector_rank
        meta["_lf_vector_score"] = r.vector_score
        meta["_lf_bm25_rank"] = r.bm25_rank
        meta["_lf_bm25_score"] = r.bm25_score
        meta["_lf_fused_rank"] = r.fused_rank
        meta["_lf_fused_score"] = r.fused_score
        meta["_lf_cross_encoder_score"] = r.cross_encoder_score
        out.append(
            RetrievedChunk(
                text=r.text,
                source=r.source,
                # Use the vector score for the engine's existing
                # confidence calculation — it remains comparable to
                # the pre-optimisation behaviour. The richer rank
                # diagnostics are in metadata.
                score=r.vector_score if r.vector_score is not None else (r.fused_score or 0.0),
                metadata=meta,
                rerank_score=r.rerank_score,
                rerank_reason=r.rerank_reason,
            )
        )

    set_run_outputs(
        n_variants=len(variants),
        n_act_filter=len(rewrite.act_keys),
        n_fused=len(fused_hits),
        n_after_rerank=len(kept),
        n_returned=len(out),
        cross_encoder=bool(enable_ce),
    )

    try:
        from app.services.metrics import metrics

        metrics.observe("rag_hybrid_total_ms", sum(timings.values()))
        metrics.inc("rag_hybrid_queries_total")
        if enable_ce:
            metrics.inc("rag_cross_encoder_queries_total")
    except Exception:  # noqa: BLE001
        pass

    return RetrievalResult(chunks=out, rewrite=rewrite, timings_ms=timings)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _apply_act_filter(
    hits: list[BM25Hit], act_keys: list[str]
) -> list[BM25Hit]:
    """Drop BM25 hits whose act_key is outside the filter set.

    Chroma's ``where`` does this natively for vector search; BM25 is in-
    process so we filter the result list explicitly. Empty filter
    means "no narrowing"; we return the input unchanged.
    """
    if not act_keys:
        return hits
    allowed = set(act_keys)
    return [h for h in hits if str(h.metadata.get("extra.act_key", "")) in allowed]


async def _overview_sample(
    act_keys: list[str],
    *,
    store: VectorStore,
    top_k: int,
) -> list[Any]:
    """Return a diversified slice of chunks belonging to ``act_keys``.

    Strategy:

    1. Pull every active chunk that belongs to one of ``act_keys`` from
       Chroma. Done in one ``get`` call so we never embed a query for
       this path.
    2. Group by source (one entry per provision) and pick the first
       chunk of each — the chunker emits provisions in act-order, so
       the first chunk of each source is typically the section heading
       + opening text, which is exactly the "what does this provision
       cover" signal the LLM needs.
    3. Cap at ``top_k`` provisions; sort by section number numerically
       so the generator can list them in natural order. The metadata
       carries the section/article number explicitly.

    Every returned chunk carries the same explainability metadata as
    the hybrid pipeline (``_lf_*``) — only the values reflect overview
    semantics (rank by section number, not by similarity). This keeps
    the panel render code identical.
    """
    from app.rag.engine import RetrievedChunk

    def _fetch_sync() -> dict[str, Any]:
        coll = store._get_collection()  # type: ignore[attr-defined]
        # ``$in`` matches any of the listed values; with a single act it
        # is equivalent to direct equality. Chroma accepts both shapes.
        where: dict[str, Any] = (
            {"extra.act_key": act_keys[0]}
            if len(act_keys) == 1
            else {"extra.act_key": {"$in": list(act_keys)}}
        )
        # Apply the active-version guard the rest of the store honours.
        try:
            return coll.get(
                where={
                    "$and": [where, {"superseded": {"$ne": True}}]
                },
                include=["documents", "metadatas"],
            )
        except Exception:  # noqa: BLE001 — older Chroma operators may not parse
            return coll.get(where=where, include=["documents", "metadatas"])

    import asyncio

    data = await asyncio.to_thread(_fetch_sync)
    ids = list(data.get("ids") or [])
    docs = list(data.get("documents") or [])
    metas = list(data.get("metadatas") or [])

    if not ids:
        return []

    # One entry per (source, chunk_index=0). Chunks with chunk_index > 0
    # are overlap continuations of the same provision — the first chunk
    # carries the heading, which is what we want.
    by_source: dict[str, dict[str, Any]] = {}
    for cid, doc, meta in zip(ids, docs, metas):
        m = meta or {}
        source = str(m.get("source", "") or "")
        if not source:
            continue
        idx = int(m.get("chunk_index", 0) or 0)
        entry = by_source.get(source)
        # Keep the chunk with the smallest chunk_index per source — that's
        # the provision's opening segment.
        if entry is None or idx < int(
            (entry["meta"] or {}).get("chunk_index", 0) or 0
        ):
            by_source[source] = {"id": cid, "doc": doc or "", "meta": m}

    entries = list(by_source.values())

    # Order by section number where possible — gives the LLM a natural
    # numeric progression rather than insertion order. Sections that
    # don't parse to a number sink to the back.
    def _sort_key(entry: dict[str, Any]) -> tuple[int, int, str]:
        m = entry["meta"] or {}
        raw = str(m.get("extra.number", "") or "")
        head = "".join(ch for ch in raw if ch.isdigit())
        tail = "".join(ch for ch in raw if not ch.isdigit())
        return (
            0 if head else 1,
            int(head) if head else 1_000_000,
            tail,
        )

    entries.sort(key=_sort_key)
    entries = entries[:top_k]

    # Translate to RetrievedChunk with the explainability metadata the
    # panel expects. Overview mode has no vector/BM25 scores; we expose
    # the section order via ``_lf_fused_rank`` so the panel still has
    # something meaningful to render.
    out: list[RetrievedChunk] = []
    for i, entry in enumerate(entries, start=1):
        meta = dict(entry["meta"] or {})
        meta["_lf_vector_rank"] = None
        meta["_lf_vector_score"] = None
        meta["_lf_bm25_rank"] = None
        meta["_lf_bm25_score"] = None
        meta["_lf_fused_rank"] = i
        meta["_lf_fused_score"] = None
        meta["_lf_cross_encoder_score"] = None
        meta["_lf_overview_pick"] = True
        out.append(
            RetrievedChunk(
                text=entry["doc"],
                source=str(meta.get("source", "")),
                # No similarity computation ran. Surface a neutral 1.0
                # so the existing confidence aggregation (mean similarity
                # of cited chunks) doesn't punish overview answers.
                score=1.0,
                metadata=meta,
                rerank_reason="overview | act-wide sample",
            )
        )
    return out


def _diversify(items: list[_Retrieved], *, k: int) -> list[_Retrieved]:
    """MMR-lite: penalise chunks that share source+section with a kept one.

    The fused list usually has near-duplicates (same provision, slightly
    different chunk boundary). Penalising them produces a more
    informative top-k for the LLM. We don't need true MMR (with vector
    inner products) because chunks from the same provision already
    cluster — comparing the ``(source, extra.number)`` tuple is
    sufficient for legal text.
    """
    if not items:
        return []
    out: list[_Retrieved] = []
    seen_keys: dict[tuple[str, str], int] = {}
    # Use cross-encoder score if present, else rerank, else fused.
    def base_score(r: _Retrieved) -> float:
        for s in (r.cross_encoder_score, r.rerank_score, r.fused_score, r.vector_score):
            if s is not None:
                return float(s)
        return 0.0

    # Walk items in their current order (which the upstream stages have
    # already prioritised). We use a soft penalty so the second-best
    # passage from a primary provision still surfaces if the alternative
    # is far weaker.
    items_with_scores = [(r, base_score(r)) for r in items]
    # Stable selection — first occurrence wins, later duplicates are
    # demoted but not removed (they may still beat a fresh source).
    for r, s in items_with_scores:
        key = (r.source, str(r.metadata.get("extra.number", "")))
        if key in seen_keys:
            r.metadata["_lf_dedup_penalty"] = DEDUP_PENALTY
            seen_keys[key] += 1
        else:
            seen_keys[key] = 1
            out.append(r)
            if len(out) >= k:
                break

    # If diversity-only selection didn't fill k, fold the demoted
    # duplicates back in (best ones first).
    if len(out) < k:
        leftover = [
            (r, s * DEDUP_PENALTY)
            for r, s in items_with_scores
            if r not in out
        ]
        leftover.sort(key=lambda pair: pair[1], reverse=True)
        for r, _ in leftover:
            out.append(r)
            if len(out) >= k:
                break

    return out


__all__ = [
    "RetrievalResult",
    "retrieve",
]
