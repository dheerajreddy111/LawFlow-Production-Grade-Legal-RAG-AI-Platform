"""
Embedding service for the LawFlow RAG pipeline.

Wraps a sentence-transformers bi-encoder behind a small async-friendly API so
the rest of the application never touches the model directly.

Model
-----
    BAAI/bge-small-en-v1.5  —  384-dim, English, retrieval-tuned.

    BGE models are trained with two conventions that materially affect recall:
        1. Embeddings should be L2-normalised so cosine similarity == dot
           product (ChromaDB's default space).
        2. *Queries* should be prefixed with a short retrieval instruction;
           *passages* should NOT.  We expose this via the ``is_query`` flag
           on embed_text() / embed_batch().

Design notes
------------
    Singleton loading
        The ~130 MB model is loaded once, lazily, on first use and guarded by
        a lock so concurrent requests during startup don't load it twice.

    Async-ready
        sentence-transformers is synchronous and CPU/GPU-bound.  Public
        methods dispatch the encode call to a thread pool via
        ``asyncio.to_thread`` (same pattern as DocumentChunker) so the event
        loop is never blocked.

    Caching
        Identical text is embedded once.  Results are memoised in a bounded,
        thread-safe LRU keyed by (model, normalize, is_query, text-hash).
        Legal corpora repeat boilerplate (headers, standard clauses) heavily,
        so the hit rate is high in practice.

ChromaDB integration hook
-------------------------
    Output is plain ``list[float]`` / ``list[list[float]]`` — directly
    accepted by ``collection.add(embeddings=...)`` / ``query_embeddings=...``.
    Use :data:`EMBEDDING_DIM` when creating the collection and pass
    ``is_query=False`` when indexing chunks, ``is_query=True`` at query time.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # avoid importing torch/transformers at module import time
    from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

MODEL_NAME: Final[str] = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
EMBEDDING_DIM: Final[int] = 384  # fixed for bge-small-en-v1.5

# Recommended retrieval instruction for BGE v1.5 (prepended to queries only).
_QUERY_INSTRUCTION: Final[str] = (
    "Represent this sentence for searching relevant passages: "
)

_CACHE_MAX_ENTRIES: Final[int] = int(os.getenv("EMBEDDING_CACHE_SIZE", "4096"))


# ── Bounded thread-safe LRU cache ─────────────────────────────────────────────

class _EmbeddingCache:
    """Minimal LRU cache for embedding vectors.

    Keys are short SHA-256 digests; values are the float vectors.  Bounded so
    a long-running process can't grow memory without limit.
    """

    def __init__(self, max_entries: int) -> None:
        self._max = max_entries
        self._store: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(text: str, *, normalize: bool, is_query: bool) -> str:
        h = hashlib.sha256()
        h.update(MODEL_NAME.encode())
        h.update(b"\x00")
        h.update(b"1" if normalize else b"0")
        h.update(b"1" if is_query else b"0")
        h.update(b"\x00")
        h.update(text.encode("utf-8"))
        return h.hexdigest()

    def get(self, key: str) -> list[float] | None:
        with self._lock:
            vec = self._store.get(key)
            if vec is None:
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return vec

    def put(self, key: str, vec: list[float]) -> None:
        with self._lock:
            self._store[key] = vec
            self._store.move_to_end(key)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "size": len(self._store),
                "max": self._max,
                "hits": self.hits,
                "misses": self.misses,
            }


# ── Embedding service ─────────────────────────────────────────────────────────

class EmbeddingService:
    """Async-friendly facade over a singleton sentence-transformers model.

    Example
    -------
        svc = EmbeddingService()                       # cheap; no model yet
        vecs = await svc.embed_batch(chunk_texts)      # index-time passages
        qvec = await svc.embed_text(user_query,        # query-time
                                    is_query=True)
    """

    # Class-level singletons: one model + one cache shared process-wide.
    _model: SentenceTransformer | None = None
    _model_lock: threading.Lock = threading.Lock()
    _cache: _EmbeddingCache = _EmbeddingCache(_CACHE_MAX_ENTRIES)

    def __init__(self, *, normalize: bool = True) -> None:
        # Normalised vectors → cosine == dot product (ChromaDB default space).
        self._normalize = normalize

    # ── model singleton ──────────────────────────────────────────────────────

    @classmethod
    def _get_model(cls) -> SentenceTransformer:
        """Lazily load the model once, thread-safely (double-checked lock)."""
        if cls._model is None:
            with cls._model_lock:
                if cls._model is None:
                    from sentence_transformers import SentenceTransformer

                    logger.info("Loading embedding model: %s", MODEL_NAME)
                    cls._model = SentenceTransformer(MODEL_NAME)
                    logger.info(
                        "Embedding model ready  dim=%d  cache_max=%d",
                        EMBEDDING_DIM,
                        _CACHE_MAX_ENTRIES,
                    )
        return cls._model

    @classmethod
    async def warmup(cls) -> None:
        """Pre-load the model (e.g. from a FastAPI lifespan handler)."""
        await asyncio.to_thread(cls._get_model)

    # ── public API ───────────────────────────────────────────────────────────

    async def embed_text(self, text: str, *, is_query: bool = False) -> list[float]:
        """Embed a single string. Returns a list of ``EMBEDDING_DIM`` floats."""
        vectors = await self.embed_batch([text], is_query=is_query)
        return vectors[0]

    async def embed_batch(
        self,
        texts: list[str],
        *,
        is_query: bool = False,
        batch_size: int = 32,
    ) -> list[list[float]]:
        """Embed many strings, preserving input order.

        Cached entries are served without touching the model; only the cache
        misses are batched through ``model.encode`` in a worker thread.
        """
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        misses: list[tuple[int, str]] = []  # (original index, key)

        for idx, text in enumerate(texts):
            key = self._cache.key(
                text, normalize=self._normalize, is_query=is_query
            )
            cached = self._cache.get(key)
            if cached is not None:
                results[idx] = cached
            else:
                misses.append((idx, key))

        if misses:
            miss_texts = [self._prepare(texts[i], is_query) for i, _ in misses]
            vectors = await asyncio.to_thread(
                self._encode_sync, miss_texts, batch_size
            )
            for (idx, key), vec in zip(misses, vectors):
                results[idx] = vec
                self._cache.put(key, vec)

        # All slots are filled at this point.
        return [vec for vec in results if vec is not None]

    @classmethod
    def cache_stats(cls) -> dict[str, int]:
        """Hit/miss/size counters — useful for ops dashboards."""
        return cls._cache.stats()

    # ── private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _prepare(text: str, is_query: bool) -> str:
        text = text.strip()
        return f"{_QUERY_INSTRUCTION}{text}" if is_query else text

    def _encode_sync(
        self, texts: list[str], batch_size: int
    ) -> list[list[float]]:
        """Blocking encode — always called inside a worker thread."""
        model = self._get_model()
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=self._normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()


# Module-level default instance for convenient import:
#   from app.rag.embeddings import embedding_service
embedding_service = EmbeddingService()
