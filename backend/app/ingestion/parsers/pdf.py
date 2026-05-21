"""PDF parser — text extraction with OCR fallback for scanned pages.

Two passes per document:

1. **Native text extraction** via PyMuPDF (fitz). Fast and lossless for
   text-bearing PDFs (typed documents, exports from Word/LibreOffice,
   judgments published as text PDFs).

2. **Per-page OCR fallback** for pages where native extraction yields
   no usable text — scanned court orders, photographed notices, image-
   only PDFs from older judgment archives. Each such page is rendered
   to a raster via :meth:`fitz.Page.get_pixmap` and passed through the
   shared OCR engine in :mod:`app.ingestion.ocr`.

The mixed-mode design preserves performance on text-bearing PDFs (no
OCR cost) while still recovering text from scanned pages. OCR is
skipped silently when the engine is unavailable — text-bearing pages
are still extracted normally.

Async-safe: native extraction and OCR both run via :func:`asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import fitz  # PyMuPDF

from app.ingestion.ocr import ocr_image, ocr_unavailable
from app.ingestion.parsers.base import BaseParser, ParseResult
from app.integrations.lc import traced

logger = logging.getLogger(__name__)


# A page yielding less than this many non-whitespace chars after native
# extraction is treated as scanned and routed through OCR (if available).
_NATIVE_TEXT_MIN_CHARS = 20

# Pixmap render scale for OCR. 2× resolution roughly doubles the visible
# glyph size — RapidOCR's accuracy improves materially at 2× without
# the cost of 3-4× rasters.
_OCR_RENDER_ZOOM = 2.0


class PDFParser(BaseParser):
    @traced(name="parser.pdf", run_type="tool")
    async def parse(self, path: Path) -> ParseResult:
        # Step 1: native text per page (off the event loop).
        native_pages: list[str] = await asyncio.to_thread(_extract_native_pages, path)
        page_count = len(native_pages)

        ocr_pages = 0
        ocr_available = not ocr_unavailable()
        rendered_pages: list[str] = list(native_pages)

        # Step 2: OCR fallback for image-only pages (if engine available).
        if ocr_available:
            scanned_indices = [
                i for i, t in enumerate(native_pages)
                if len(t.strip()) < _NATIVE_TEXT_MIN_CHARS
            ]
            if scanned_indices:
                logger.info(
                    "PDF %s: %d page(s) routed to OCR fallback",
                    path.name,
                    len(scanned_indices),
                )
                ocr_results = await _ocr_pages(path, scanned_indices)
                for idx, ocr_text in zip(scanned_indices, ocr_results):
                    if ocr_text.strip():
                        rendered_pages[idx] = ocr_text
                        ocr_pages += 1

        text = "\n\n".join(p for p in rendered_pages if p.strip())
        return ParseResult(
            text=text,
            page_count=page_count,
            extra={
                "ocr_pages": ocr_pages,
                "native_text_pages": sum(
                    1 for p in native_pages if len(p.strip()) >= _NATIVE_TEXT_MIN_CHARS
                ),
                "ocr_available": ocr_available,
            },
        )


def _extract_native_pages(path: Path) -> list[str]:
    doc = fitz.open(str(path))
    try:
        return [page.get_text() for page in doc]
    finally:
        doc.close()


async def _ocr_pages(path: Path, indices: list[int]) -> list[str]:
    """Render each indexed page to PNG bytes and OCR it.

    Rendering is dispatched off the event loop. OCR is dispatched per
    page so a single slow page can't starve the others when the runtime
    grows a worker pool.
    """
    pngs: list[bytes] = await asyncio.to_thread(_render_pages_sync, path, indices)
    texts: list[str] = []
    for png in pngs:
        if not png:
            texts.append("")
            continue
        result = await ocr_image(png)
        texts.append(result.text)
    return texts


def _render_pages_sync(path: Path, indices: list[int]) -> list[bytes]:
    """Render the requested page indices to PNG bytes (in order)."""
    out: list[bytes] = []
    doc = fitz.open(str(path))
    try:
        mat = fitz.Matrix(_OCR_RENDER_ZOOM, _OCR_RENDER_ZOOM)
        for idx in indices:
            try:
                page = doc[idx]
                pix = page.get_pixmap(matrix=mat, alpha=False)
                # PyMuPDF writes PNG via pix.tobytes; the API has been
                # stable across versions but guard against malformed pages.
                out.append(pix.tobytes("png"))
            except Exception as exc:  # noqa: BLE001 — boundary
                logger.warning(
                    "Failed to render page %d of %s for OCR (%s: %s)",
                    idx,
                    path.name,
                    type(exc).__name__,
                    exc,
                )
                out.append(b"")
    finally:
        doc.close()
    return out
