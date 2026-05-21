"""Plain-text parser — reads the file as UTF-8 with replacement on decode errors.

Reading is dispatched to asyncio.to_thread so large files don't block the
event loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.ingestion.parsers.base import BaseParser, ParseResult


class TXTParser(BaseParser):
    async def parse(self, path: Path) -> ParseResult:
        text = await asyncio.to_thread(
            path.read_text, encoding="utf-8", errors="replace"
        )
        return ParseResult(text=text)
