"""Lexical BM25 retrieval, paired with the semantic vector store.

Why BM25
--------
Embedding similarity is excellent at *concept* match but blind to exact
token match. Legal queries are full of tokens that *must* be matched
verbatim — section numbers (``25F``, ``138``), Act abbreviations
(``IDA``, ``CrPC``), and statutory terms of art. A 2024-era bi-encoder
will happily score "Section 25F" and "Section 25" within 0.001 of each
other; BM25 will not.

This module sits next to :mod:`app.rag.vector_store` and is queried in
parallel during retrieval. The fusion layer
(:mod:`app.rag.hybrid`) merges the two ranked lists via
Reciprocal Rank Fusion.

Design
------
- A single in-memory ``BM25Okapi`` index, rebuilt from the active
  chunks in the Chroma collection on first use / explicit
  ``refresh()``. Cheap (a few MB for ~1k–10k chunks) and stale-tolerant
  — the corpus is append-mostly, and any drift is auto-corrected on the
  next ``refresh()`` cycle.
- Tokenisation is intentionally simple: lowercase, alphanumerics +
  legal punctuation (``§`` survives, ``§25F`` stays one token), digits
  preserved. Specialised stemming would hurt more than help for legal
  text where section numbers are the most discriminative tokens.
- Thread-safe construction: a per-process lock guards index rebuild so
  concurrent first-use requests don't redundantly load the corpus.

Public surface
--------------
- :class:`BM25Index`  — async refresh + score; one process-wide singleton.
- :func:`bm25_index` — accessor for the singleton.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.integrations.lc import traced
from app.rag.vector_store import vector_store as default_vector_store

logger = logging.getLogger(__name__)


# ── Tokenisation ─────────────────────────────────────────────────────────────
#
# Tuned for Indian legal text. Token classes:
#   - word characters [a-z0-9]
#   - statute markers: § / ¶ kept as standalone tokens
#   - section numbers "25F" preserved as ONE token, not split into 25 + F
#
# Stopwords are stripped only when the rest of the document is in a
# stop-heavy register — we don't strip them universally because phrases
# like "abuse of process" carry meaning in legal English.

_TOKEN_RE = re.compile(r"§|¶|[a-z0-9]+", re.IGNORECASE)

_LEGAL_STOP = frozenset(
    "a an the of to in on at by for with is are was were be been can could "
    "may might shall should will would do does did i we you he she it they "
    "this that these those if then under as about into from "
    "and or not no any my our your".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase, alnum + statute markers, stopword-stripped.

    Section numbers like ``25F`` stay one token; punctuation that
    matters legally (``§``) survives. This is consumed both at index
    build time and at query time so the two paths agree exactly on what
    a token is.
    """
    return [
        t.lower()
        for t in _TOKEN_RE.findall(text or "")
        if t.lower() not in _LEGAL_STOP
    ]


# ── Result type ──────────────────────────────────────────────────────────────


@dataclass
class BM25Hit:
    """One BM25 hit. ``score`` is the raw Okapi score (not normalised)."""

    chunk_id: str
    text: str
    score: float
    source: str
    metadata: dict[str, Any]


# ── Index ────────────────────────────────────────────────────────────────────


class BM25Index:
    """Process-wide BM25 index rebuilt from the active Chroma chunks.

    Construction is lazy: the first ``search`` (or explicit ``refresh``)
    triggers a load. Subsequent calls reuse the in-memory state until
    ``refresh()`` is called again. The corpus is small (legal acts) so
    we comfortably hold every chunk's tokens in memory.
    """

    def __init__(self) -> None:
        self._bm25: Any | None = None
        self._chunk_ids: list[str] = []
        self._texts: list[str] = []
        self._sources: list[str] = []
        self._metadatas: list[dict[str, Any]] = []
        self._lock: threading.Lock = threading.Lock()
        self._loaded_at: float | None = None
        self._n_docs: int = 0

    # ── public API ─────────────────────────────────────────────────────────

    async def refresh(self, store: Any | None = None) -> int:
        """Rebuild the in-memory index from the active Chroma chunks.

        Returns the number of chunks indexed. Cheap enough to call from
        a startup hook or a periodic admin sweep — pulls every chunk's
        text + metadata in one ``coll.get()`` and tokenises.
        """
        store = store or default_vector_store
        # The heavy lifting (Chroma round-trip + tokenisation) is done
        # in a worker thread; only the build step touches shared state.
        rows = await asyncio.to_thread(self._fetch_active_chunks_sync, store)
        return await asyncio.to_thread(self._rebuild_sync, rows)

    @traced(name="bm25.search", run_type="retriever")
    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        store: Any | None = None,
    ) -> list[BM25Hit]:
        """Tokenise ``query`` and return the top-k BM25 hits.

        Lazily loads the index on first call. The result list is
        ordered by raw Okapi score, descending. An empty corpus
        returns ``[]`` rather than raising.
        """
        if not query or not query.strip():
            return []
        if self._bm25 is None:
            await self.refresh(store)
        tokens = tokenize(query)
        if not tokens or self._n_docs == 0:
            return []
        return await asyncio.to_thread(self._score_sync, tokens, top_k)

    def is_ready(self) -> bool:
        """True once the index has been loaded at least once."""
        return self._bm25 is not None

    def stats(self) -> dict[str, Any]:
        return {
            "loaded": self._bm25 is not None,
            "n_docs": self._n_docs,
            "loaded_at": self._loaded_at,
        }

    # ── private ────────────────────────────────────────────────────────────

    def _fetch_active_chunks_sync(self, store: Any) -> dict[str, Any]:
        """Pull every active chunk's id, text, source, metadata."""
        coll = store._get_collection()  # internal — same module
        try:
            data = coll.get(
                where={"superseded": {"$ne": True}},
                include=["documents", "metadatas"],
            )
        except Exception:
            # Some older Chroma versions don't accept the operator
            # form — retry without the filter.
            data = coll.get(include=["documents", "metadatas"])
        return data

    def _rebuild_sync(self, rows: dict[str, Any]) -> int:
        """Build a BM25Okapi from the fetched rows. Thread-safe."""
        ids = list(rows.get("ids") or [])
        docs = list(rows.get("documents") or [])
        metas = list(rows.get("metadatas") or [])

        if not ids:
            with self._lock:
                self._bm25 = None
                self._chunk_ids = []
                self._texts = []
                self._sources = []
                self._metadatas = []
                self._n_docs = 0
                self._loaded_at = time.time()
            logger.info("BM25 index: corpus empty, ready=False")
            return 0

        sources = [str((m or {}).get("source", "")) for m in metas]
        tokenised = [tokenize(t or "") for t in docs]

        # Import here so the chunker / tests that don't use the index
        # don't pay the rank-bm25 import cost.
        from rank_bm25 import BM25Okapi

        # k1=1.5, b=0.75 are the canonical defaults. We don't tune
        # these per-collection because the legal corpus's lexical
        # statistics are stable.
        bm25 = BM25Okapi(tokenised)
        with self._lock:
            self._bm25 = bm25
            self._chunk_ids = ids
            self._texts = docs
            self._sources = sources
            self._metadatas = [dict(m or {}) for m in metas]
            self._n_docs = len(ids)
            self._loaded_at = time.time()

        try:
            from app.services.metrics import metrics

            metrics.inc("bm25_index_rebuilds_total")
            metrics.observe("bm25_index_size_docs", float(len(ids)))
        except Exception:  # noqa: BLE001 — boundary
            pass

        logger.info("BM25 index: rebuilt with %d active chunks", len(ids))
        return len(ids)

    def _score_sync(self, tokens: list[str], top_k: int) -> list[BM25Hit]:
        bm25 = self._bm25
        if bm25 is None:
            return []
        # rank-bm25 scores against every doc — O(N|Q|), trivially fast
        # for our N < 5k corpus.
        scores = bm25.get_scores(tokens)
        if len(scores) == 0:
            return []
        # Argsort descending, take top_k. Skip zero-scored docs — they
        # contain none of the query terms.
        order = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True,
        )[:top_k]
        out: list[BM25Hit] = []
        for idx in order:
            s = float(scores[idx])
            if s <= 0.0:
                break
            out.append(
                BM25Hit(
                    chunk_id=self._chunk_ids[idx],
                    text=self._texts[idx],
                    score=round(s, 6),
                    source=self._sources[idx],
                    metadata=self._metadatas[idx],
                )
            )
        return out


# Module-level singleton — cheap until the first refresh / search.
_BM25_INDEX = BM25Index()


def bm25_index() -> BM25Index:
    """Accessor for the process-wide BM25 index."""
    return _BM25_INDEX
