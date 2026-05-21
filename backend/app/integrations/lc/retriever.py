"""LangChain ``BaseRetriever`` over the existing :class:`VectorStore`.

The wrapper is a *thin adapter* — embedding, persistence, and reranking
stay in their authoritative modules:

- :mod:`app.rag.embeddings`     produces vectors (BAAI/bge-small)
- :mod:`app.rag.vector_store`   persists + searches them (ChromaDB)
- :mod:`app.rag.rerank`         re-scores top-k with legal signals

This adapter only translates between LangChain's :class:`Document`
contract and LawFlow's :class:`SearchResult` / :class:`RetrievedChunk`.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForRetrieverRun,
    CallbackManagerForRetrieverRun,
)
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.rag.engine import RetrievedChunk
from app.rag.rerank import RAG_RETRIEVE_K
from app.rag.rerank import rerank as deterministic_rerank
from app.rag.vector_store import SearchResult, VectorStore, vector_store

logger = logging.getLogger(__name__)


def _search_to_document(hit: SearchResult) -> Document:
    """Translate a VectorStore hit into a LangChain Document.

    Preserves the cosine score in ``metadata["_score"]`` and the source
    in ``metadata["source"]`` so downstream LangChain consumers and the
    LangGraph nodes can pull it back out.
    """
    meta = dict(hit.metadata or {})
    meta.setdefault("source", hit.source)
    meta["chunk_id"] = hit.chunk_id
    meta["_score"] = float(hit.score)
    return Document(page_content=hit.text, metadata=meta)


def _document_to_chunk(doc: Document) -> RetrievedChunk:
    """Reverse adapter: LangChain Document → existing RetrievedChunk.

    Used by the LangGraph rerank node so the existing
    :func:`app.rag.rerank.rerank` (operates on ``RetrievedChunk``) can
    score the documents without being rewritten.
    """
    meta = dict(doc.metadata or {})
    return RetrievedChunk(
        text=doc.page_content,
        source=str(meta.get("source", "")),
        score=float(meta.get("_score", 0.0)),
        metadata=meta,
    )


def _chunk_to_document(chunk: RetrievedChunk) -> Document:
    """Reverse adapter: RetrievedChunk → LangChain Document.

    Preserves rerank explainability (``_rerank_score``, ``_rerank_reason``)
    in metadata when the rerank pass has populated them.
    """
    meta = dict(chunk.metadata or {})
    meta.setdefault("source", chunk.source)
    meta["_score"] = float(chunk.score)
    if chunk.rerank_score is not None:
        meta["_rerank_score"] = float(chunk.rerank_score)
    if chunk.rerank_reason is not None:
        meta["_rerank_reason"] = chunk.rerank_reason
    return Document(page_content=chunk.text, metadata=meta)


class LawFlowRetriever(BaseRetriever):
    """LangChain retriever backed by :class:`VectorStore`.

    Parameters
    ----------
    store
        The VectorStore to query (default: process-wide singleton).
    top_k
        Number of initial vector hits to fetch — typically the wide
        ``RAG_RETRIEVE_K`` for downstream reranking, or a smaller value
        for direct use.
    use_rerank
        When ``True``, the deterministic reranker is applied before
        results are returned (1–3 strongest on-point passages). When
        ``False``, the raw top-k vector hits are returned (the graph
        applies its own rerank node so callers in the graph keep this
        ``False``).
    jurisdiction
        Optional Chroma metadata filter on ``extra.jurisdiction``.

    Notes
    -----
    The retriever satisfies LangChain's runnable protocol — it traces
    automatically when LangSmith callbacks are attached. No additional
    instrumentation is needed here.
    """

    # Pydantic v2 model config — accept arbitrary attribute types and
    # let BaseRetriever's hooks resolve normally.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    store: VectorStore = Field(default=vector_store)
    top_k: int = Field(default=RAG_RETRIEVE_K)
    use_rerank: bool = Field(default=False)
    jurisdiction: str | None = Field(default=None)

    # ── sync (delegates to async via LangChain's wrapper) ────────────────────

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        # Sync path is not used in the FastAPI request flow (async only),
        # but LangChain requires the implementation. Defer to the simplest
        # blocking equivalent: schedule the async coroutine.
        import asyncio

        return asyncio.run(
            self._aget_relevant_documents(query, run_manager=run_manager)  # type: ignore[arg-type]
        )

    async def _aget_relevant_documents(
        self,
        query: str,
        *,
        run_manager: AsyncCallbackManagerForRetrieverRun,
    ) -> list[Document]:
        if not query or not query.strip():
            return []

        where: dict[str, Any] | None = (
            {"extra.jurisdiction": self.jurisdiction} if self.jurisdiction else None
        )
        hits: list[SearchResult] = await self.store.similarity_search(
            query, top_k=self.top_k, where=where
        )
        docs = [_search_to_document(h) for h in hits]

        if self.use_rerank and docs:
            chunks = [_document_to_chunk(d) for d in docs]
            reranked = deterministic_rerank(query, chunks)
            docs = [_chunk_to_document(c) for c in reranked]

        return docs


def build_retriever(
    *,
    top_k: int | None = None,
    use_rerank: bool = False,
    jurisdiction: str | None = None,
) -> LawFlowRetriever:
    """Convenience factory — most callers should use this."""
    return LawFlowRetriever(
        store=vector_store,
        top_k=top_k if top_k is not None else RAG_RETRIEVE_K,
        use_rerank=use_rerank,
        jurisdiction=jurisdiction,
    )
