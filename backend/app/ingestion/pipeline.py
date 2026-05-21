"""
IngestionPipeline — orchestrates upload storage and text extraction.

Flow per document:
    1. Validate file extension → select parser
    2. Read upload bytes → enforce size limit
    3. Persist to uploads/ directory with a UUID prefix (prevents collisions)
    4. Dispatch to the appropriate parser (PDF / DOCX / TXT)
    5. Return IngestResult with filename, stored path, text, and metadata

Design notes:
    • The upload directory is created at construction; no per-request I/O setup.
    • All blocking operations (file write, parsing) are off-loaded via
      asyncio.to_thread so the FastAPI event loop is never stalled.
    • Embeddings and vector-store indexing are intentionally absent here;
      they will be added in the RAG phase as a post-parse step.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Final
from uuid import uuid4

from fastapi import UploadFile
from pydantic import BaseModel

from app.ingestion.parsers.base import BaseParser
from app.ingestion.parsers.csv import CSVParser
from app.ingestion.parsers.docx import DOCXParser
from app.ingestion.parsers.image import ImageParser
from app.ingestion.parsers.pdf import PDFParser
from app.ingestion.parsers.txt import TXTParser
from app.ingestion.parsers.xlsx import XLSXParser
from app.integrations.lc import traced
from app.services.metrics import metrics

# ── Constants ─────────────────────────────────────────────────────────────────

_MAX_FILE_BYTES: Final[int] = 50 * 1024 * 1024  # 50 MB

# Default upload dir: backend/uploads/  (two parents above app/ingestion/)
_DEFAULT_UPLOAD_DIR: Final[Path] = (
    Path(__file__).resolve().parent.parent.parent / "uploads"
)

_MIME_BY_EXT: Final[dict[str, str]] = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt":  "text/plain",
    ".md":   "text/markdown",
    ".csv":  "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png":  "image/png",
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tiff": "image/tiff",
    ".tif":  "image/tiff",
    ".bmp":  "image/bmp",
    ".webp": "image/webp",
}

# Built once at module load; parsers are stateless, safe to share.
# The same ImageParser instance is reused for every image extension —
# the OCR engine is loaded lazily on first call (one-time cost).
_image_parser = ImageParser()
_PARSERS: Final[dict[str, BaseParser]] = {
    ".pdf":  PDFParser(),
    ".docx": DOCXParser(),
    ".txt":  TXTParser(),
    # Markdown is plain text from an extraction standpoint — defer to TXTParser.
    ".md":   TXTParser(),
    ".csv":  CSVParser(),
    ".xlsx": XLSXParser(),
    ".png":  _image_parser,
    ".jpg":  _image_parser,
    ".jpeg": _image_parser,
    ".tiff": _image_parser,
    ".tif":  _image_parser,
    ".bmp":  _image_parser,
    ".webp": _image_parser,
}


# ── Domain exceptions ─────────────────────────────────────────────────────────

class IngestionError(Exception):
    """Base class for ingestion failures."""


class UnsupportedFileTypeError(IngestionError):
    def __init__(self, ext: str) -> None:
        super().__init__(
            f"Unsupported file type {ext!r}. "
            f"Accepted: {', '.join(_PARSERS)}"
        )
        self.ext = ext


class FileTooLargeError(IngestionError):
    def __init__(self, size: int, limit: int) -> None:
        super().__init__(
            f"File size {size:,} bytes exceeds the {limit // (1024 * 1024)} MB limit."
        )
        self.size  = size
        self.limit = limit


# ── Public result types ───────────────────────────────────────────────────────

class DocumentMetadata(BaseModel):
    content_type: str
    file_size:    int         # bytes
    page_count:   int | None  # PDF / image; None for DOCX / TXT / CSV / XLSX
    word_count:   int
    char_count:   int
    uploaded_at:  str         # ISO-8601 UTC
    # Format-specific extras passed through from the parser's ParseResult.
    # Examples:
    #   PDF:   {"ocr_pages": 2, "native_text_pages": 8, "ocr_available": true}
    #   XLSX:  {"sheet_count": 3, "sheets": [...], "row_count_total": 412}
    #   CSV:   {"row_count": 1023, "columns": [...], "has_header": true}
    #   image: {"ocr": true, "ocr_avg_confidence": 0.94, "image_width": 1654}
    #   url:   {"source_url": "...", "title": "...", "language": "en"}
    parser_extras: dict = {}


class IngestResult(BaseModel):
    filename:  str   # original upload filename
    stored_as: str   # UUID-prefixed name on disk
    text:      str   # full extracted plain text
    metadata:  DocumentMetadata


# ── Pipeline ──────────────────────────────────────────────────────────────────

class IngestionPipeline:
    """Stateless ingestion orchestrator — safe to share across async tasks."""

    def __init__(self, upload_dir: Path = _DEFAULT_UPLOAD_DIR) -> None:
        self._upload_dir = upload_dir
        self._upload_dir.mkdir(parents=True, exist_ok=True)

    @traced(name="ingestion.pipeline.ingest", run_type="chain")
    async def ingest(self, upload: UploadFile) -> IngestResult:
        async with metrics.timer("ingest_ms"):
            return await self._ingest_inner(upload)

    async def _ingest_inner(self, upload: UploadFile) -> IngestResult:
        filename = upload.filename or "upload"
        ext      = Path(filename).suffix.lower()

        # 1. Select parser (validates extension implicitly)
        parser = _PARSERS.get(ext)
        if parser is None:
            metrics.inc("ingest_unsupported", ext=ext or "<none>")
            raise UnsupportedFileTypeError(ext)

        # 2. Read and size-check
        content = await upload.read()
        if len(content) > _MAX_FILE_BYTES:
            metrics.inc("ingest_too_large")
            raise FileTooLargeError(len(content), _MAX_FILE_BYTES)

        # 3. Persist (blocking write dispatched off the event loop)
        stored_name = f"{uuid4().hex}_{filename}"
        dest        = self._upload_dir / stored_name
        await asyncio.to_thread(dest.write_bytes, content)

        # 4. Parse
        parse_result = await parser.parse(dest)
        text         = parse_result.text

        # 5. Build result — parser_extras carries format-specific metadata
        # (OCR stats, sheet counts, row counts, …) without breaking the
        # existing schema (still typed as DocumentMetadata with the same
        # mandatory fields).
        metadata = DocumentMetadata(
            content_type=upload.content_type or _MIME_BY_EXT.get(ext, "application/octet-stream"),
            file_size=len(content),
            page_count=parse_result.page_count,
            word_count=len(text.split()),
            char_count=len(text),
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            parser_extras=dict(parse_result.extra or {}),
        )

        # Observability — per-extension ingestion counters + size histogram.
        metrics.inc("ingest_total", ext=ext.lstrip("."))
        metrics.observe("ingest_bytes", float(len(content)), ext=ext.lstrip("."))

        return IngestResult(
            filename=filename,
            stored_as=stored_name,
            text=text,
            metadata=metadata,
        )
