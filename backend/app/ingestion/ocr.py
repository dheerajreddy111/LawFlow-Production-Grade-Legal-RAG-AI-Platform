"""Shared OCR helper used by the image and PDF parsers.

Backed by ``rapidocr-onnxruntime`` — pure-Python, runs on the ONNX
runtime that ChromaDB already pulls in, no system binary required.
Lives in its own module so the image parser and the PDF scanned-page
fallback share a single engine instance (model load is the expensive
part; one instance per process is enough).

Design contract
---------------
- All blocking work runs inside ``asyncio.to_thread``.
- The engine is constructed lazily on first call and cached at module
  scope so the model load cost is paid once.
- :func:`ocr_unavailable` lets callers degrade gracefully when the
  package isn't installed (CI / minimal images).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class OCRResult:
    """One OCR pass over an image. ``text`` joins lines top-to-bottom."""

    text: str
    line_count: int
    avg_confidence: float | None  # 0..1; None when engine returns no scores


_engine: Any | None = None
_engine_failed: bool = False


def _get_engine() -> Any | None:
    """Return the cached RapidOCR engine; ``None`` if unavailable."""
    global _engine, _engine_failed
    if _engine is not None:
        return _engine
    if _engine_failed:
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
        logger.info("RapidOCR engine ready")
        return _engine
    except Exception as exc:  # noqa: BLE001 — boundary: degrade gracefully
        _engine_failed = True
        logger.warning(
            "OCR unavailable (%s: %s) — install rapidocr-onnxruntime to enable",
            type(exc).__name__,
            exc,
        )
        return None


def ocr_unavailable() -> bool:
    """True when the OCR engine cannot be loaded (package missing, etc.)."""
    return _get_engine() is None


def _run_engine_sync(image_input: Any) -> OCRResult:
    """Run the engine over a file path or PIL Image; return joined text."""
    engine = _get_engine()
    if engine is None:
        return OCRResult(text="", line_count=0, avg_confidence=None)

    # rapidocr accepts a path (str), bytes, or numpy array. PIL Image is
    # not directly supported — we convert to bytes (PNG) and pass.
    if hasattr(image_input, "save") and not isinstance(image_input, (str, Path, bytes)):
        buf = BytesIO()
        image_input.save(buf, format="PNG")
        image_input = buf.getvalue()
    elif isinstance(image_input, Path):
        image_input = str(image_input)

    raw, _elapsed = engine(image_input)
    if not raw:
        return OCRResult(text="", line_count=0, avg_confidence=None)

    lines: list[str] = []
    scores: list[float] = []
    for entry in raw:
        # Output shape: [[bbox], "text", confidence]; engine versions vary.
        try:
            _bbox, text, score = entry[0], entry[1], entry[2]
        except (IndexError, TypeError):
            continue
        text_s = (text or "").strip()
        if text_s:
            lines.append(text_s)
        try:
            scores.append(float(score))
        except (TypeError, ValueError):
            pass

    avg_conf = round(sum(scores) / len(scores), 4) if scores else None
    return OCRResult(
        text="\n".join(lines),
        line_count=len(lines),
        avg_confidence=avg_conf,
    )


async def ocr_image(image: Any) -> OCRResult:
    """OCR a single image (path, bytes, or PIL Image). Off the event loop."""
    return await asyncio.to_thread(_run_engine_sync, image)
