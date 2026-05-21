"""
Abstract base for all document parsers.

Each concrete parser accepts a file path and returns a ParseResult containing
the extracted plain text plus any format-specific metadata (page count, etc.).
All parse methods are async; CPU-bound work must be dispatched via
asyncio.to_thread so the event loop stays unblocked.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParseResult:
    text:       str
    page_count: int | None          = None
    extra:      dict[str, object]   = field(default_factory=dict)


class BaseParser(ABC):
    @abstractmethod
    async def parse(self, path: Path) -> ParseResult: ...
