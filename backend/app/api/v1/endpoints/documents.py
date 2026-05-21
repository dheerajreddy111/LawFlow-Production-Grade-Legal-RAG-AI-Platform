"""
Document ingestion endpoints.

- ``POST /api/v1/documents/upload``     file upload (PDF, DOCX, TXT, CSV,
                                        XLSX, PNG, JPG, TIFF, BMP, WEBP)
- ``POST /api/v1/documents/ingest-url`` direct URL ingestion (legal pages
                                        with boilerplate stripped)

The response shape is the existing :class:`IngestResult`. Format-specific
parser metadata (OCR stats, sheet counts, source URL, …) lives under
``metadata.parser_extras`` so the front-end can render rich provenance
without breaking older clients.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.auth import User, current_user, require_admin
from app.ingestion.pipeline import (
    DocumentMetadata,
    FileTooLargeError,
    IngestionPipeline,
    IngestResult,
    UnsupportedFileTypeError,
)
from app.ingestion.url import (
    URLExtractionError,
    URLFetchError,
    URLIngestionError,
    URLTooLargeError,
    fetch_url,
)
from app.rag.chunker import ChunkConfig, DocumentChunker
from app.rag.vector_store import vector_store
from app.rag.versioning import VersionedIngestResult, ingest_versioned_text

router    = APIRouter()
_pipeline = IngestionPipeline()
# A modest chunk size for user uploads — longer than the corpus default
# because user documents (judgments, contracts) carry more narrative.
_USER_CHUNKER = DocumentChunker(ChunkConfig(max_chars=1400, overlap=200))


class _UploadResponse(BaseModel):
    """Upload response, extended with optional versioning info."""

    filename: str
    stored_as: str
    text: str
    metadata: DocumentMetadata
    versioning: VersionedIngestResult | None = None


@router.post(
    "/upload",
    response_model=_UploadResponse,
    summary="Upload and extract text from a legal document",
)
async def upload_document(
    _admin: Annotated[User, Depends(require_admin)],
    file: UploadFile = File(
        ...,
        description="PDF, DOCX, TXT, CSV, XLSX, PNG, JPG, TIFF, BMP, WEBP — max 50 MB",
    ),
    persist: bool = Query(
        False,
        description="When true, chunk + embed + persist the document into the "
        "vector store with version tracking. Older revisions of the same "
        "source are marked superseded automatically.",
    ),
) -> _UploadResponse:
    try:
        result = await _pipeline.ingest(file)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    versioning: VersionedIngestResult | None = None
    if persist and result.text.strip():
        versioning = await ingest_versioned_text(
            vector_store,
            _USER_CHUNKER,
            text=result.text,
            source=result.filename,
            extra={
                "uploaded_filename": result.filename,
                "content_type": result.metadata.content_type,
            },
        )

    return _UploadResponse(
        filename=result.filename,
        stored_as=result.stored_as,
        text=result.text,
        metadata=result.metadata,
        versioning=versioning,
    )


# ── Version inspection ──────────────────────────────────────────────────────


class _VersionEntry(BaseModel):
    version_id: str
    version: int
    superseded: bool
    ingested_at: str | None = None
    chunk_count: int


class _VersionsResponse(BaseModel):
    source: str
    versions: list[_VersionEntry]


@router.get(
    "/versions",
    response_model=_VersionsResponse,
    summary="List ingested versions of a document (newest, active first)",
)
async def list_document_versions(
    _user: Annotated[User, Depends(current_user)],
    source: str = Query(..., description="Document source identifier (filename)"),
) -> _VersionsResponse:
    versions = await vector_store.versions_for(source)
    return _VersionsResponse(
        source=source,
        versions=[_VersionEntry(**v) for v in versions],
    )


# ── URL ingestion ────────────────────────────────────────────────────────────


class URLIngestRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)
    persist: bool = Field(
        False,
        description="When true, chunk + embed + persist the page into the "
        "vector store with version tracking. The page URL is the "
        "versioning source identifier.",
    )


@router.post(
    "/ingest-url",
    response_model=_UploadResponse,
    summary="Fetch a legal web page and extract clean article text",
)
async def ingest_url(
    body: URLIngestRequest,
    _admin: Annotated[User, Depends(require_admin)],
) -> _UploadResponse:
    """Direct URL ingestion: fetch + extract main article text.

    Boilerplate (nav, ads, related stories) is removed by trafilatura;
    only the substantive page body is kept. The response uses the same
    :class:`_UploadResponse` shape as file upload — ``stored_as`` is the
    final URL (after redirects) since no file is persisted on disk. The
    final URL also doubles as the versioning source identifier when
    ``persist=true``.
    """
    try:
        result = await fetch_url(body.url)
    except URLTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except URLFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except URLExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except URLIngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    text = result.text
    metadata = DocumentMetadata(
        content_type=result.content_type or "text/html",
        file_size=result.fetched_bytes,
        page_count=None,
        word_count=len(text.split()),
        char_count=len(text),
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        parser_extras={
            "source_url": result.url,
            "title": result.title,
            "language": result.language,
            **result.metadata,
        },
    )

    versioning: VersionedIngestResult | None = None
    if body.persist and text.strip():
        versioning = await ingest_versioned_text(
            vector_store,
            _USER_CHUNKER,
            text=text,
            source=result.url,
            extra={
                "source_url": result.url,
                "title": result.title,
                "language": result.language,
            },
        )

    return _UploadResponse(
        filename=result.title or result.url,
        stored_as=result.url,
        text=text,
        metadata=metadata,
        versioning=versioning,
    )
