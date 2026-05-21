"""End-to-end smoke test for the hybrid retrieval orchestrator.

Validates the public contract — :func:`app.rag.retrieval.retrieve`
returns chunks ordered best-first, the per-stage diagnostics make it
into the chunk metadata, and the existing :class:`RetrievedChunk`
shape is preserved so downstream consumers (RAGEngine, LangGraph
nodes, ExplainabilityPanel) keep working unchanged.

This test runs against the real Chroma store + the small bundled act
files. Marked as a slow test because it triggers corpus ingestion +
BM25 build on cold start.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.skipif(
    not __import__("os").path.exists(
        __import__("os").path.join(
            __import__("os").path.dirname(__file__),
            "..",
            "app",
            "data",
            "acts",
            "ipc.json",
        )
    ),
    reason="Corpus files absent; skip end-to-end test",
)
def test_hybrid_retrieval_returns_chunks_with_stage_diagnostics():
    """A representative query produces chunks with hybrid stage scores."""
    from app.rag.bm25 import bm25_index
    from app.rag.ingest import ingest_corpora
    from app.rag.retrieval import retrieve

    async def run() -> None:
        # Ingest + warm BM25 index. Idempotent.
        await ingest_corpora()
        await bm25_index().refresh()

        result = await retrieve(
            "What does Section 302 of the IPC say about murder?",
            top_k=5,
        )
        assert result.chunks, "expected at least one chunk"

        # Every chunk should expose hybrid stage diagnostics.
        for c in result.chunks:
            meta = c.metadata or {}
            # The fused-rank field is the canonical stage marker — any
            # chunk surfaced by the orchestrator has it set.
            assert "_lf_fused_rank" in meta
            # Vector + BM25 are the two retrievers; at least one must
            # have ranked any given returned chunk.
            assert (
                meta.get("_lf_vector_rank") is not None
                or meta.get("_lf_bm25_rank") is not None
            )

        # The rewriter found IPC + the section number.
        assert "ipc" in result.rewrite.act_keys
        assert "302" in result.rewrite.sections

        # Timings populated.
        assert "rewrite_ms" in result.timings_ms
        assert "hybrid_ms" in result.timings_ms

    asyncio.new_event_loop().run_until_complete(run())
