"""Document versioning helpers — track active vs. superseded revisions.

Versioning model
----------------
Every chunk written to the vector store carries four fields (see
:class:`app.rag.chunker.ChunkMetadata`):

    version_id   SHA-256 hex of the full source text — uniquely
                 identifies a revision of a document.
    version      1-based revision number, monotonic per ``source``.
    superseded   ``True`` when a newer revision of the same source
                 exists; the retriever filters these out by default.
    ingested_at  ISO-8601 UTC timestamp of when the chunks were written.

Workflow for a versioned ingest of a document with ``source = S``:

    1. Compute ``version_id_new = sha256(text)``.
    2. Look up the most recent active revision for ``S`` from the
       vector store (``list_versions``).
    3. If ``version_id_new`` equals the latest active version, the
       upload is a no-op (idempotent — same content).
    4. Otherwise, mark every chunk under ``source == S`` as
       ``superseded=True`` (``supersede_source``).
    5. Stamp the new chunks with ``version_id_new``, ``version =
       latest_version + 1``, ``superseded = False``, ``ingested_at = now``.
    6. Upsert via :meth:`VectorStore.add_chunks`.

The retrieval default is "active only" — :meth:`VectorStore.similarity_search`
filters ``superseded=True`` out unless ``include_superseded=True`` is
explicitly passed.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.integrations.lc import traced
from app.rag.chunker import DocumentChunk


def compute_version_id(text: str) -> str:
    """Stable 16-char hex hash of a document's full text.

    Two ingests of identical content produce the same version_id; one
    character change produces a different one. The 16-char prefix of
    SHA-256 gives 64 bits of collision space — enough for a
    per-document version registry.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def stamp_chunks(
    chunks: list[DocumentChunk],
    *,
    version_id: str,
    version: int = 1,
    superseded: bool = False,
    ingested_at: str | None = None,
) -> list[DocumentChunk]:
    """Set version metadata on a list of freshly-chunked DocumentChunks.

    Returns the same list with each chunk's metadata mutated in place;
    return-value is provided for chaining.
    """
    ts = ingested_at or datetime.now(timezone.utc).isoformat()
    for chunk in chunks:
        chunk.metadata.version_id = version_id
        chunk.metadata.version = version
        chunk.metadata.superseded = superseded
        chunk.metadata.ingested_at = ts
    return chunks


async def list_versions(store, source: str) -> list[dict[str, Any]]:
    """Return every distinct version of ``source`` known to the store.

    Each entry: ``{version_id, version, superseded, ingested_at,
    chunk_count}``, ordered most-recent first. Empty list when the
    source has never been ingested.
    """
    versions = await store.versions_for(source)
    return versions


async def supersede_source(store, source: str) -> int:
    """Mark every chunk under ``source`` as superseded.

    Returns the number of chunks updated. Idempotent: re-marking
    already-superseded chunks is a no-op.
    """
    return await store.mark_superseded(source)


from dataclasses import dataclass


@dataclass
class VersionedIngestResult:
    source: str
    version_id: str
    version: int
    chunks_added: int
    chunks_superseded: int
    is_new_version: bool   # False when the upload was a no-op (same content)


@traced(name="versioning.ingest_versioned_text", run_type="chain")
async def ingest_versioned_text(
    store,
    chunker,
    *,
    text: str,
    source: str,
    extra: dict[str, Any] | None = None,
) -> VersionedIngestResult:
    """Version-aware ingestion of a single parsed document.

    Workflow
    --------
    1. Compute ``version_id`` from ``text``.
    2. List existing versions for ``source``.
    3. If the most-recent active version equals the new ``version_id``,
       the upload is a no-op (same content, idempotent).
    4. Otherwise, mark every existing chunk for ``source`` as
       superseded, then chunk + stamp + upsert the new revision.

    Returns a summary the caller can surface in the response.
    """
    if not text or not text.strip():
        return VersionedIngestResult(
            source=source,
            version_id=compute_version_id(""),
            version=1,
            chunks_added=0,
            chunks_superseded=0,
            is_new_version=False,
        )

    new_version_id = compute_version_id(text)
    existing = await store.versions_for(source)
    active_versions = [v for v in existing if not v.get("superseded")]
    latest_version_num = max((v["version"] for v in existing), default=0)

    if active_versions and active_versions[0].get("version_id") == new_version_id:
        # Same content already active — true no-op.
        return VersionedIngestResult(
            source=source,
            version_id=new_version_id,
            version=int(active_versions[0]["version"]),
            chunks_added=0,
            chunks_superseded=0,
            is_new_version=False,
        )

    superseded_count = 0
    if existing:
        superseded_count = await store.mark_superseded(source)

    new_chunks = await chunker.chunk(text, source=source, extra=extra or {})
    stamp_chunks(
        new_chunks,
        version_id=new_version_id,
        version=int(latest_version_num) + 1,
        superseded=False,
    )
    added = await store.add_chunks(new_chunks)

    return VersionedIngestResult(
        source=source,
        version_id=new_version_id,
        version=int(latest_version_num) + 1,
        chunks_added=added,
        chunks_superseded=superseded_count,
        is_new_version=True,
    )
