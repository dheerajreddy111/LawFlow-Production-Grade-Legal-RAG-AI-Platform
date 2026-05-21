"""
Corpus ingestion: load every JSON act in app/data/acts/ into the vector
store so RAG-routed queries can do real semantic retrieval.

Pipeline (per provision):
    JSON corpus → chunk (DocumentChunker) → embed (EmbeddingService,
    inside VectorStore.add_chunks) → persist (ChromaDB).

Each chunk carries metadata for filtering / citation rendering:
    act name, section/article number, legal domain, citations, unit.

Idempotent: ChromaDB upserts by deterministic chunk_id, and a populated
collection is skipped unless ``force=True``. Safe to call on every boot.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from app.rag.chunker import ChunkConfig, DocumentChunk, DocumentChunker
from app.rag.vector_store import VectorStore, vector_store
from app.rag.versioning import compute_version_id, stamp_chunks
from app.services.act_registry import ACT_REGISTRY, domain_for

logger = logging.getLogger(__name__)

_ACTS_DIR: Final[Path] = (
    Path(__file__).resolve().parent.parent / "data" / "acts"
)

# Provisions are short, self-contained statutory text — keep one chunk per
# provision where possible so a retrieved hit maps cleanly to a section.
# The 1200-char window deliberately exceeds the global default (800) so a
# single mid-length provision stays whole; the overlap is small because
# corpus provisions don't bleed across boundaries.
_CHUNKER = DocumentChunker(ChunkConfig(max_chars=1200, overlap=120, fold_below=180))


def _build_chunks_for_act(act_key: str, ingested_at: str) -> list[DocumentChunk]:
    spec = ACT_REGISTRY[act_key]
    raw_text = (_ACTS_DIR / spec.filename).read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    unit = spec.unit  # "section" | "article"
    domain = domain_for(act_key)

    # One version_id per act file — content-derived so a corpus update
    # naturally produces a new revision when the JSON changes.
    act_version_id = compute_version_id(raw_text)

    chunks: list[DocumentChunk] = []
    for entry in raw.get("sections", []):
        number = str(entry["number"])
        title = entry["title"]
        unit_label = "Article" if unit == "article" else "Section"
        # Source string doubles as the citation label in retrieval results.
        source = f"{spec.name} — {unit_label} {number}: {title}"
        keywords: list[str] = list(entry.get("keywords") or [])

        # Embedded text: title + keyword string + content. The keyword
        # line gives BM25 a deterministic lexical handle for queries that
        # use plain-language synonyms (e.g. "stealing" matches a §378
        # chunk whose keywords list includes "stealing"). The same line
        # also nudges the bi-encoder toward terse provisions.
        keyword_line = (
            f"Keywords: {', '.join(keywords)}\n\n" if keywords else ""
        )
        text = (
            f"{unit_label} {number} — {title}\n\n"
            f"{keyword_line}"
            f"{entry['content']}"
        )

        produced = _CHUNKER._chunk_sync(
            text,
            source,
            {
                "act": spec.name,
                "act_key": act_key,
                "number": number,
                "title": title,
                "unit": unit,
                "domain": domain,
                "citations": entry.get("citations", []),
                # Persisted so BM25 reconstruction + metadata-aware
                # retrieval can use them at query time.
                "keywords": keywords,
            },
        )
        # Stamp every chunk produced for this act with the file's
        # version_id, so similarity_search's active-version filter keeps
        # them visible by default.
        stamp_chunks(
            produced,
            version_id=act_version_id,
            version=1,
            superseded=False,
            ingested_at=ingested_at,
        )
        chunks.extend(produced)
    return chunks


async def ingest_corpora(
    store: VectorStore = vector_store,
    *,
    force: bool = False,
) -> int:
    """Ingest all registered corpora. Returns the number of chunks persisted.

    No-op (returns existing count) when the collection is already populated
    AND every existing chunk already carries the new version metadata.
    When the collection pre-dates the versioning fields, we transparently
    force a one-time re-ingest so retrieval's active-version filter
    continues to see those chunks.
    """
    stats = await store.collection_stats()
    if stats.get("count", 0) > 0 and not force:
        has_versions = await store.has_version_metadata()
        has_keywords = await store.has_keywords_metadata()
        # Detect when ``ACT_REGISTRY`` has gained an act that the
        # on-disk Chroma index doesn't carry — the trigger for a
        # forced re-ingest after the corpus expansion pass.
        present_keys = await store.get_act_keys()
        expected_keys = set(ACT_REGISTRY.keys())
        missing_keys = expected_keys - present_keys

        if has_versions and has_keywords and not missing_keys:
            logger.info(
                "Corpus already ingested (%d chunks, %d acts) — skipping",
                stats["count"],
                len(present_keys),
            )
            return int(stats["count"])
        if not has_versions:
            logger.info(
                "Corpus present but lacks version metadata — backfilling "
                "(this is a one-time migration)"
            )
        if not has_keywords:
            logger.info(
                "Corpus present but lacks keyword-enriched chunks — "
                "purging + re-ingesting to pick up the retrieval "
                "optimisation pass"
            )
            # New chunks have different IDs (text changed → first-200-char
            # hash drifts) so a plain upsert would leave the old chunks
            # behind. Empty the collection before re-ingesting.
            await store.reset_collection()
        elif missing_keys:
            logger.info(
                "Corpus missing %d act(s) (%s) — purging + re-ingesting",
                len(missing_keys),
                ", ".join(sorted(missing_keys)),
            )
            # Same reset rationale: when existing acts were also expanded,
            # an upsert would leave the older, leaner chunks alongside.
            await store.reset_collection()

    ingested_at = datetime.now(timezone.utc).isoformat()
    all_chunks: list[DocumentChunk] = []
    for act_key in ACT_REGISTRY:
        act_chunks = _build_chunks_for_act(act_key, ingested_at)
        all_chunks.extend(act_chunks)
        logger.info(
            "Prepared %d chunks for '%s'", len(act_chunks), act_key
        )

    persisted = await store.add_chunks(all_chunks)
    logger.info(
        "Corpus ingestion complete: %d chunks across %d acts",
        persisted,
        len(ACT_REGISTRY),
    )
    return persisted
