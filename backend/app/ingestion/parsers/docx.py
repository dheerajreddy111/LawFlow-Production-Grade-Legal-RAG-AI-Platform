"""DOCX parser — uses python-docx for text extraction.

Paragraphs are joined with blank lines; empty paragraphs (section breaks,
blank lines in the original) are filtered out.  Tables are not extracted
in this foundation pass — add table iteration when the use-case demands it.
python-docx is synchronous and I/O-bound, so parsing runs inside
asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from docx import Document

from app.ingestion.parsers.base import BaseParser, ParseResult


class DOCXParser(BaseParser):
    async def parse(self, path: Path) -> ParseResult:
        return await asyncio.to_thread(_parse_sync, path)


def _parse_sync(path: Path) -> ParseResult:
    doc        = Document(str(path))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text       = "\n\n".join(paragraphs)
    return ParseResult(text=text)
