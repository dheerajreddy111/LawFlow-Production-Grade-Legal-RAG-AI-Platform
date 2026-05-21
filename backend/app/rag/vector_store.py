"""
ChromaDB vector store for the LawFlow RAG pipeline.

Persists embedded legal-document chunks and serves semantic similarity
search.  Sits between the chunker/embedder and the RAG engine:

    DocumentChunker.chunk()  →  list[DocumentChunk]
                                      │
                                      ▼
                          VectorStore.add_chunks()
                          (EmbeddingService embeds; Chroma persists)
                                      │
                                      ▼
                       VectorStore.similarity_search(query)
                                      │
                                      ▼
                              RAGEngine.retrieve()

Design notes
------------
    Persistence
        Uses ``chromadb.PersistentClient`` so the index survives restarts.
        Storage dir is ``CHROMA_DIR`` (env) or ``app/data/chroma`` by default.

    Embeddings
        Vectors are produced by :class:`EmbeddingService`
        (BAAI/bge-small-en-v1.5, L2-normalised).  We pass embeddings to Chroma
        explicitly and never register a Chroma embedding function — the model
        lives in exactly one place.  Cosine space is configured to match the
        normalised vectors.

    Async-ready
        The Chroma client is synchronous.  Every public method dispatches its
        blocking work to a worker thread via ``asyncio.to_thread`` (same
        pattern as DocumentChunker / EmbeddingService) so the event loop is
        never blocked.

    Metadata filtering (future)
        Chroma metadata values must be scalar (str | int | float | bool) and
        non-null.  :func:`_flatten_metadata` projects ChunkMetadata into that
        shape — top-level fields kept as-is, ``extra.*`` flattened with a
        prefix, ``None`` dropped, non-scalars JSON-stringified.  This keeps
        ``source``, ``chunk_index``, ``strategy``, ``section_title`` and any
        scalar ``extra`` field directly usable in a Chroma ``where=`` clause
        once jurisdiction/date filtering is wired into the engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from app.integrations.lc import traced
from app.rag.chunker import ChunkMetadata, DocumentChunk
from app.rag.embeddings import EMBEDDING_DIM, EmbeddingService, embedding_service

if TYPE_CHECKING:  # avoid importing chromadb at module import time
    from chromadb.api import ClientAPI
    from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

_DEFAULT_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "data" / "chroma"
CHROMA_DIR: Final[str] = os.getenv("CHROMA_DIR", str(_DEFAULT_DIR))
COLLECTION_NAME: Final[str] = os.getenv("CHROMA_COLLECTION", "lawflow_legal_corpus")


# ── Public result type ────────────────────────────────────────────────────────

@dataclass
class SearchResult:
    """One hit from similarity_search, ordered most-relevant first.

    ``score`` is cosine similarity in [0, 1] (1 == identical direction),
    derived from Chroma's cosine distance.  ``metadata`` is the flattened
    payload — use :meth:`as_chunk_metadata` to recover the original model.
    """
    chunk_id: str
    text:     str
    score:    float
    source:   str
    metadata: dict[str, Any]


# ── Metadata projection ───────────────────────────────────────────────────────

_SCALAR = (str, int, float, bool)


def _flatten_metadata(meta: ChunkMetadata) -> dict[str, Any]:
    """Project ChunkMetadata into Chroma-safe scalar metadata.

    Rules: keep scalar top-level fields; flatten ``extra`` under an
    ``extra.`` prefix; drop ``None`` (Chroma rejects null values);
    JSON-stringify anything non-scalar so it round-trips losslessly.
    """
    flat: dict[str, Any] = {}

    base = meta.model_dump(exclude={"extra"})
    for key, value in base.items():
        if value is None:
            continue
        flat[key] = value if isinstance(value, _SCALAR) else json.dumps(value)

    for key, value in meta.extra.items():
        if value is None:
            continue
        ck = f"extra.{key}"
        flat[ck] = value if isinstance(value, _SCALAR) else json.dumps(value)

    return flat


# ── Vector store ──────────────────────────────────────────────────────────────

class VectorStore:
    """Async-friendly facade over a persistent ChromaDB collection.

    Example
    -------
        store = VectorStore()                       # cheap; no client yet
        await store.add_chunks(chunks)              # embed + persist
        hits = await store.similarity_search(q, top_k=5)
        await store.delete_document("judgment_2024.pdf")
    """

    # Process-wide singletons: one persistent client + one collection handle.
    _client: ClientAPI | None = None

    def __init__(
        self,
        *,
        collection_name: str = COLLECTION_NAME,
        embedder: EmbeddingService = embedding_service,
    ) -> None:
        self._collection_name = collection_name
        self._embedder = embedder
        self._collection: Collection | None = None

    # ── client / collection singletons ───────────────────────────────────────

    @classmethod
    def _get_client(cls) -> ClientAPI:
        if cls._client is None:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            Path(CHROMA_DIR).mkdir(parents=True, exist_ok=True)
            logger.info("Opening ChromaDB persistent store at %s", CHROMA_DIR)
            cls._client = chromadb.PersistentClient(
                path=CHROMA_DIR,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return cls._client

    def _get_collection(self) -> Collection:
        """Get-or-create the collection (cosine space → normalised vectors)."""
        if self._collection is None:
            client = self._get_client()
            self._collection = client.get_or_create_collection(
                name=self._collection_name,
                metadata={
                    "hnsw:space": "cosine",
                    "embedding_model": self._embedder.__class__.__name__,
                    "embedding_dim": EMBEDDING_DIM,
                },
            )
            logger.info(
                "Collection ready  name=%s  count=%d",
                self._collection_name,
                self._collection.count(),
            )
        return self._collection

    async def warmup(self) -> None:
        """Open the store and the embedding model up front (lifespan hook)."""
        await asyncio.to_thread(self._get_collection)
        await self._embedder.warmup()

    # ── public API ───────────────────────────────────────────────────────────

    async def add_chunks(self, chunks: list[DocumentChunk]) -> int:
        """Embed and upsert chunks. Returns the number persisted.

        Idempotent: ``chunk_id`` is the Chroma primary key, so re-ingesting
        the same document overwrites rather than duplicates.  Each chunk's
        ``metadata.embedding_id`` is set to its ``chunk_id`` (the vector-store
        key) — the hook DocumentChunker documents.
        """
        if not chunks:
            return 0

        texts = [c.text for c in chunks]
        embeddings = await self._embedder.embed_batch(texts, is_query=False)

        ids: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for chunk in chunks:
            chunk.metadata.embedding_id = chunk.chunk_id
            ids.append(chunk.chunk_id)
            metadatas.append(_flatten_metadata(chunk.metadata))

        await asyncio.to_thread(
            self._upsert_sync, ids, texts, embeddings, metadatas
        )
        logger.info("Upserted %d chunks into %s", len(ids), self._collection_name)
        return len(ids)

    @traced(name="vector_store.similarity_search", run_type="retriever")
    async def similarity_search(
        self,
        query: str,
        *,
        top_k: int = 5,
        where: dict[str, Any] | None = None,
        include_superseded: bool = False,
    ) -> list[SearchResult]:
        """Semantic search. ``where`` is a Chroma metadata filter (optional).

        The query is embedded with the BGE query instruction
        (``is_query=True``); results are returned most-relevant first.

        By default, chunks whose ``superseded`` metadata is ``True`` are
        excluded — this is the active-version-only retrieval contract.
        Pass ``include_superseded=True`` to retrieve across all
        revisions (e.g. for audit / version-history views).
        """
        if not query.strip():
            return []

        merged_where = _merge_active_filter(where, include_superseded)
        query_embedding = await self._embedder.embed_text(query, is_query=True)
        raw = await asyncio.to_thread(
            self._query_sync, query_embedding, top_k, merged_where
        )

        ids = (raw.get("ids") or [[]])[0]
        docs = (raw.get("documents") or [[]])[0]
        metas = (raw.get("metadatas") or [[]])[0]
        dists = (raw.get("distances") or [[]])[0]

        results: list[SearchResult] = []
        for cid, doc, meta, dist in zip(ids, docs, metas, dists):
            meta = meta or {}
            results.append(
                SearchResult(
                    chunk_id=cid,
                    text=doc or "",
                    # cosine distance → similarity in [0, 1]
                    score=round(1.0 - float(dist), 6),
                    source=str(meta.get("source", "")),
                    metadata=dict(meta),
                )
            )
        return results

    async def delete_document(self, source: str) -> None:
        """Delete every chunk belonging to a source document."""
        await asyncio.to_thread(self._delete_sync, source)
        logger.info("Deleted all chunks for source=%s", source)

    async def collection_stats(self) -> dict[str, Any]:
        """Count, collection name, embedding dim, and on-disk location."""
        count = await asyncio.to_thread(lambda: self._get_collection().count())
        return {
            "collection": self._collection_name,
            "count": count,
            "embedding_dim": EMBEDDING_DIM,
            "path": CHROMA_DIR,
        }

    async def list_sources_summary(self) -> list[dict[str, Any]]:
        """Per-source aggregate: chunks + active-chunk count + latest version.

        Loads every chunk's metadata (no embeddings) so it is O(N) in
        collection size. Acceptable for tens of thousands of chunks; if
        the corpus grows past that we should add a side-index. Used by
        the admin dashboard's Overview + Documents pages.
        """
        return await asyncio.to_thread(self._list_sources_summary_sync)

    # ── versioning ───────────────────────────────────────────────────────────

    async def has_version_metadata(self) -> bool:
        """Best-effort check that existing chunks carry version fields.

        Used by the corpus bootstrap to decide whether to force a
        re-ingest (so legacy chunks gain ``superseded`` / ``version_id``
        defaults). Returns ``False`` when the collection is empty.
        """
        sample = await asyncio.to_thread(self._peek_sync, 1)
        metas = sample.get("metadatas") or []
        if not metas:
            return False
        first = metas[0] or {}
        return "superseded" in first or "version_id" in first

    async def has_keywords_metadata(self) -> bool:
        """True when an existing chunk carries the per-provision keywords list.

        Pre-dates the retrieval optimisation pass — chunks ingested
        before then lack ``extra.keywords`` (and their embedded text
        lacks the ``Keywords:`` line that boosts BM25 recall). The
        corpus bootstrap uses this to decide whether to force a
        one-time re-ingest.
        """
        sample = await asyncio.to_thread(self._peek_sync, 1)
        metas = sample.get("metadatas") or []
        if not metas:
            return False
        first = metas[0] or {}
        return "extra.keywords" in first

    async def get_act_keys(self) -> set[str]:
        """Return the distinct ``extra.act_key`` values present in the store.

        Used by the corpus bootstrap to detect when a new act has been
        added to ``ACT_REGISTRY`` but the on-disk Chroma index still
        reflects an older corpus — that's the trigger for a forced
        re-ingest with ``reset_collection``.
        """
        try:
            data = await asyncio.to_thread(
                lambda: self._get_collection().get(include=["metadatas"])
            )
        except Exception:  # noqa: BLE001 — defensive: empty / corrupt collection
            return set()
        metas = list(data.get("metadatas") or [])
        keys: set[str] = set()
        for m in metas:
            k = (m or {}).get("extra.act_key")
            if k:
                keys.add(str(k))
        return keys

    async def reset_collection(self) -> None:
        """Drop every chunk in the collection (irreversible).

        Used by the corpus bootstrap when the chunker output schema
        changes — old chunks would otherwise linger alongside the
        re-ingested ones (their IDs differ because chunk text changed).
        Production callers should only invoke this from idempotent
        ingestion paths.
        """
        await asyncio.to_thread(self._reset_collection_sync)
        logger.warning("VectorStore: reset_collection called — collection emptied")

    async def mark_superseded(self, source: str) -> int:
        """Set ``superseded=True`` on every chunk under ``source``.

        Returns the number of chunks updated. Idempotent.
        """
        updated = await asyncio.to_thread(self._mark_superseded_sync, source)
        if updated:
            logger.info(
                "Marked %d chunks as superseded for source=%s", updated, source
            )
        return updated

    async def versions_for(self, source: str) -> list[dict[str, Any]]:
        """Distinct versions ingested for a source, newest-first.

        Each entry: ``{version_id, version, superseded, ingested_at,
        chunk_count}``. Empty list when ``source`` is unknown.
        """
        return await asyncio.to_thread(self._versions_for_sync, source)

    # ── private (always run inside a worker thread) ──────────────────────────

    def _upsert_sync(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        self._get_collection().upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def _query_sync(
        self,
        query_embedding: list[float],
        top_k: int,
        where: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._get_collection().query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )

    def _delete_sync(self, source: str) -> None:
        self._get_collection().delete(where={"source": source})

    def _reset_collection_sync(self) -> None:
        """Drop and recreate the collection — wipes every chunk.

        We delete the collection entirely (rather than walk every id and
        call ``delete``) because Chroma's bulk delete on huge ID lists
        is expensive and the collection's HNSW params should be
        preserved exactly as the get_or_create-time config — which
        recreation re-applies.
        """
        client = self._get_client()
        try:
            client.delete_collection(self._collection_name)
        except Exception:  # noqa: BLE001 — boundary: missing collection is fine
            pass
        # Drop the cached handle so the next _get_collection() recreates it
        # with the same metadata (hnsw:space, embedding_dim, …) as before.
        self._collection = None

    def _peek_sync(self, n: int) -> dict[str, Any]:
        """Best-effort sample of stored chunks for schema introspection."""
        try:
            return self._get_collection().peek(limit=n)
        except Exception:  # noqa: BLE001 — defensive: old Chroma versions
            try:
                return self._get_collection().get(limit=n)
            except Exception:  # noqa: BLE001 — boundary
                return {}

    def _mark_superseded_sync(self, source: str) -> int:
        coll = self._get_collection()
        existing = coll.get(where={"source": source})
        ids = list(existing.get("ids") or [])
        if not ids:
            return 0
        old_metas = list(existing.get("metadatas") or [])
        new_metas: list[dict[str, Any]] = []
        for meta in old_metas:
            m = dict(meta or {})
            m["superseded"] = True
            new_metas.append(m)
        coll.update(ids=ids, metadatas=new_metas)
        return len(ids)

    def _versions_for_sync(self, source: str) -> list[dict[str, Any]]:
        coll = self._get_collection()
        existing = coll.get(where={"source": source})
        metas = list(existing.get("metadatas") or [])
        if not metas:
            return []

        # Group by version_id; aggregate count + read shared fields.
        buckets: dict[str, dict[str, Any]] = {}
        for meta in metas:
            m = meta or {}
            vid = str(m.get("version_id") or "<legacy>")
            entry = buckets.setdefault(
                vid,
                {
                    "version_id": vid,
                    "version": int(m.get("version", 1) or 1),
                    "superseded": bool(m.get("superseded", False)),
                    "ingested_at": m.get("ingested_at"),
                    "chunk_count": 0,
                },
            )
            entry["chunk_count"] += 1
            # Prefer the latest seen non-None timestamp.
            if m.get("ingested_at"):
                entry["ingested_at"] = m["ingested_at"]

        # Sort: active (not superseded) first, then by ingested_at desc, then version desc.
        return sorted(
            buckets.values(),
            key=lambda e: (
                e["superseded"],
                -(int(e["version"]) if isinstance(e["version"], int) else 0),
                -1 if not e["ingested_at"] else 0,
            ),
        )

    def _list_sources_summary_sync(self) -> list[dict[str, Any]]:
        coll = self._get_collection()
        try:
            data = coll.get(include=["metadatas"])
        except Exception:  # noqa: BLE001 — boundary: defensive against driver shape changes
            return []
        metas = list(data.get("metadatas") or [])
        if not metas:
            return []

        bucket: dict[str, dict[str, Any]] = {}
        for meta in metas:
            m = meta or {}
            source = str(m.get("source") or "<unknown>")
            entry = bucket.setdefault(
                source,
                {
                    "source": source,
                    "chunks_total": 0,
                    "chunks_active": 0,
                    "versions": 0,
                    "latest_ingested_at": None,
                    "_version_ids": set(),
                },
            )
            entry["chunks_total"] += 1
            if not m.get("superseded"):
                entry["chunks_active"] += 1
            vid = m.get("version_id")
            if vid:
                entry["_version_ids"].add(str(vid))
            ingested = m.get("ingested_at")
            if ingested and (
                entry["latest_ingested_at"] is None
                or ingested > entry["latest_ingested_at"]
            ):
                entry["latest_ingested_at"] = ingested

        out: list[dict[str, Any]] = []
        for entry in bucket.values():
            entry["versions"] = len(entry["_version_ids"]) or 1
            entry.pop("_version_ids", None)
            out.append(entry)
        # Newest-touched first, then alphabetical for determinism.
        out.sort(
            key=lambda e: (
                -1 if e["latest_ingested_at"] else 0,
                e["latest_ingested_at"] or "",
                e["source"],
            ),
            reverse=True,
        )
        return out


# ── Filter helpers ───────────────────────────────────────────────────────────

def _merge_active_filter(
    where: dict[str, Any] | None,
    include_superseded: bool,
) -> dict[str, Any] | None:
    """Merge an active-version filter into a caller's ``where`` clause.

    When ``include_superseded`` is True, returns ``where`` unchanged.
    Otherwise composes ``{"$and": [where, {"superseded": {"$ne": True}}]}``,
    which excludes ``superseded=True`` while still matching chunks that
    pre-date this field (treated as active by default).
    """
    if include_superseded:
        return where
    active_clause = {"superseded": {"$ne": True}}
    if not where:
        return active_clause
    # If caller already filters on superseded, respect their choice.
    if "superseded" in where:
        return where
    return {"$and": [where, active_clause]}


# Module-level default instance for convenient import:
#   from app.rag.vector_store import vector_store
vector_store = VectorStore()
