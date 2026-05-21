"""Image parser — OCR for direct image uploads (PNG / JPG / TIFF / BMP).

Covers the "court notice / photographed page" use case: a user
photographs a printed notice and uploads it. The parser routes the
image through the shared OCR engine in :mod:`app.ingestion.ocr` and
returns the recognised text as plain text. Visual layout
reconstruction is intentionally out of scope here — the chunker and
RAG path already handle line-broken text well.

Graceful degradation: when the OCR engine cannot be loaded (package
missing on a minimal image), the parser returns empty text plus
``ocr_unavailable=True`` in extra so the API can return a clear error
instead of a silent failure.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.ingestion.ocr import OCRResult, ocr_image, ocr_unavailable
from app.ingestion.parsers.base import BaseParser, ParseResult
from app.integrations.lc import traced


class ImageParser(BaseParser):
    @traced(name="parser.image", run_type="tool")
    async def parse(self, path: Path) -> ParseResult:
        if ocr_unavailable():
            return ParseResult(
                text="",
                extra={
                    "ocr": False,
                    "ocr_unavailable": True,
                    "reason": "OCR engine not installed — install "
                    "rapidocr-onnxruntime to enable scanned-document parsing.",
                },
            )

        # Open once to capture dimensions; pass the same image object
        # to the OCR engine to avoid a re-read.
        with Image.open(path) as img:
            img.load()
            width, height = img.size
            mode = img.mode
            # rapidocr expects RGB; convert defensively.
            if mode not in {"RGB", "RGBA"}:
                rgb = img.convert("RGB")
            else:
                rgb = img
            result: OCRResult = await ocr_image(rgb)

        return ParseResult(
            text=result.text,
            page_count=1,
            extra={
                "ocr": True,
                "ocr_line_count": result.line_count,
                "ocr_avg_confidence": result.avg_confidence,
                "image_width": width,
                "image_height": height,
                "image_mode": mode,
            },
        )
