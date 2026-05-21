"""Admin document-management endpoints.

- ``GET    /documents``           list every source in the vector store
- ``GET    /documents/{source}``  per-source detail with version history
- ``DELETE /documents/{source}``  remove every chunk for a source
- ``POST   /documents/upload``    upload + persist a corpus document

Upload is an *operational* surface: the admin UI lets an operator add
new corpus material without shell access. It reuses the same
ingestion pipeline + versioning helper as ``POST /api/v1/documents/
upload`` — this route is a thin admin-namespaced wrapper that always
persists (no extract-only mode) and returns an operator-friendly
response shape.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Path, UploadFile, status
from pydantic import BaseModel

from app.auth import User, require_admin
from app.ingestion.pipeline import (
    FileTooLargeError,
    IngestionPipeline,
    UnsupportedFileTypeError,
)
from app.rag.chunker import ChunkConfig, DocumentChunker
from app.rag.vector_store import vector_store
from app.rag.versioning import ingest_versioned_text

router = APIRouter()

# Module-level singletons — both are stateless / thread-safe and cheap
# to share across requests. Same chunker config as the existing
# user-facing /api/v1/documents/upload endpoint so the corpus stays
# consistent regardless of which surface ingested a document.
_pipeline = IngestionPipeline()
_corpus_chunker = DocumentChunker(ChunkConfig(max_chars=1400, overlap=200))


# ── Response shapes ─────────────────────────────────────────────────────────


class DocumentItem(BaseModel):
    """One row in the admin documents table."""

    source: str
    chunks_total: int
    chunks_active: int
    versions: int
    latest_ingested_at: str | None = None


class DocumentsListResponse(BaseModel):
    documents: list[DocumentItem]
    total: int  # convenience: documents.length (saves a UI calc)


class DocumentVersionEntry(BaseModel):
    version_id: str
    version: int
    superseded: bool
    ingested_at: str | None = None
    chunk_count: int


class DocumentDetail(BaseModel):
    source: str
    chunks_total: int
    chunks_active: int
    versions: list[DocumentVersionEntry]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _normalise_versions(raw: list[dict[str, Any]]) -> list[DocumentVersionEntry]:
    out: list[DocumentVersionEntry] = []
    for v in raw:
        out.append(
            DocumentVersionEntry(
                version_id=str(v.get("version_id") or "<legacy>"),
                version=int(v.get("version", 1) or 1),
                superseded=bool(v.get("superseded", False)),
                ingested_at=v.get("ingested_at"),
                chunk_count=int(v.get("chunk_count", 0) or 0),
            )
        )
    return out


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get(
    "/documents",
    response_model=DocumentsListResponse,
    summary="List every document indexed in the vector store",
)
async def list_documents(
    _admin: Annotated[User, Depends(require_admin)],
) -> DocumentsListResponse:
    rows = await vector_store.list_sources_summary()
    items = [
        DocumentItem(
            source=r["source"],
            chunks_total=int(r.get("chunks_total", 0)),
            chunks_active=int(r.get("chunks_active", 0)),
            versions=int(r.get("versions", 1)),
            latest_ingested_at=r.get("latest_ingested_at"),
        )
        for r in rows
    ]
    return DocumentsListResponse(documents=items, total=len(items))


@router.get(
    "/documents/{source:path}",
    response_model=DocumentDetail,
    summary="Per-source detail with full version history",
)
async def document_detail(
    _admin: Annotated[User, Depends(require_admin)],
    source: Annotated[str, Path(description="Document source identifier (filename or URL)")],
) -> DocumentDetail:
    versions_raw = await vector_store.versions_for(source)
    if not versions_raw:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No chunks found for source {source!r}",
        )
    versions = _normalise_versions(versions_raw)
    chunks_total = sum(v.chunk_count for v in versions)
    chunks_active = sum(v.chunk_count for v in versions if not v.superseded)
    return DocumentDetail(
        source=source,
        chunks_total=chunks_total,
        chunks_active=chunks_active,
        versions=versions,
    )


@router.delete(
    "/documents/{source:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete every chunk for a source",
)
async def delete_document(
    _admin: Annotated[User, Depends(require_admin)],
    source: Annotated[str, Path(description="Document source identifier")],
) -> None:
    existing = await vector_store.versions_for(source)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No chunks found for source {source!r}",
        )
    await vector_store.delete_document(source)


# ── Upload ──────────────────────────────────────────────────────────────────


class AdminUploadResponse(BaseModel):
    """Operator-facing response for a corpus upload.

    ``status`` is "ingested" on a successful new ingestion (chunks
    added to the corpus) or "noop" when the upload was idempotent
    against the latest version (same content already on file). 422 is
    returned for empty / unparseable files; 415 for unsupported
    extensions; 413 for oversized uploads.
    """

    source: str
    stored_as: str
    status: str  # "ingested" | "noop"
    chunks_created: int
    chunks_superseded: int
    version: int
    version_id: str
    is_new_version: bool
    file_size: int
    word_count: int
    char_count: int
    latency_ms: float


@router.post(
    "/documents/upload",
    response_model=AdminUploadResponse,
    summary="Upload a document and ingest it into the corpus (admin-only)",
)
async def upload_document(
    _admin: Annotated[User, Depends(require_admin)],
    file: UploadFile = File(
        ...,
        description=(
            "Corpus document to ingest. Supported: pdf, docx, txt, md, csv, "
            "xlsx, png/jpg/jpeg/tiff/tif/bmp/webp (OCR). Max 50 MB."
        ),
    ),
) -> AdminUploadResponse:
    started = time.perf_counter()
    try:
        result = await _pipeline.ingest(file)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)
        ) from exc

    text = result.text
    if not text.strip():
        # The parser ran but produced no usable text (empty / image-only
        # PDF with OCR disabled, etc.). Refuse silently-succeeding ingest.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No text could be extracted from the file. "
            "Upload a document with extractable content.",
        )

    versioning = await ingest_versioned_text(
        vector_store,
        _corpus_chunker,
        text=text,
        source=result.filename,
        extra={
            "uploaded_filename": result.filename,
            "content_type": result.metadata.content_type,
        },
    )
    latency_ms = round((time.perf_counter() - started) * 1000.0, 2)

    return AdminUploadResponse(
        source=versioning.source,
        stored_as=result.stored_as,
        status="ingested" if versioning.is_new_version else "noop",
        chunks_created=versioning.chunks_added,
        chunks_superseded=versioning.chunks_superseded,
        version=versioning.version,
        version_id=versioning.version_id,
        is_new_version=versioning.is_new_version,
        file_size=result.metadata.file_size,
        word_count=result.metadata.word_count,
        char_count=result.metadata.char_count,
        latency_ms=latency_ms,
    )
