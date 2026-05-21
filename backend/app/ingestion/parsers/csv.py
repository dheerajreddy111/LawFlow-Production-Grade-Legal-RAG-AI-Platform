"""CSV parser — row-aware, async-safe.

Uses Python's stdlib ``csv`` module (no extra dependency). The parsed
text is rendered one row per line in the form
``"<col1>: <val1> | <col2>: <val2>"`` so:

- Chunking respects row boundaries (each row reads as a self-contained
  sentence after the chunker's whitespace normalisation).
- Header context is preserved with every row, which improves retrieval
  quality on tabular legal data (FIR registers, cause lists, fine
  schedules).

Row-level metadata (row_count, columns, has_header, sample row) is
exposed via :attr:`ParseResult.extra` so downstream consumers can
filter / display table provenance.
"""

from __future__ import annotations

import asyncio
import csv
import io
from pathlib import Path

from app.ingestion.parsers.base import BaseParser, ParseResult
from app.integrations.lc import traced

_MAX_FIELD_BYTES = 1_000_000  # 1 MB per cell — keeps the parser robust
csv.field_size_limit(_MAX_FIELD_BYTES)


def _looks_like_header(row: list[str]) -> bool:
    """Heuristic: a header row has non-empty, mostly-non-numeric cells."""
    if not row:
        return False
    cells = [c.strip() for c in row]
    non_empty = [c for c in cells if c]
    if len(non_empty) < max(1, len(cells) // 2):
        return False
    numeric = sum(1 for c in non_empty if c.replace(".", "", 1).lstrip("-").isdigit())
    return numeric < len(non_empty) / 2


def _render(row: list[str], header: list[str] | None) -> str:
    """One CSV row → one self-contained text line."""
    if header and len(header) == len(row):
        return " | ".join(f"{(h or '').strip()}: {(v or '').strip()}" for h, v in zip(header, row))
    return " | ".join((v or "").strip() for v in row)


class CSVParser(BaseParser):
    @traced(name="parser.csv", run_type="tool")
    async def parse(self, path: Path) -> ParseResult:
        return await asyncio.to_thread(_parse_sync, path)


def _parse_sync(path: Path) -> ParseResult:
    raw = path.read_text(encoding="utf-8", errors="replace")
    # Sniff dialect from the first ~4 KB; fall back to excel dialect on
    # ambiguous input (one-column CSV, single line, etc.).
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(raw), dialect=dialect)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return ParseResult(text="", extra={"row_count": 0, "columns": []})

    has_header = _looks_like_header(rows[0])
    header = rows[0] if has_header else None
    data_rows = rows[1:] if has_header else rows

    # Rows are joined with blank lines so the chunker treats each as a
    # paragraph (preserves boundaries when a window covers many rows).
    lines = [_render(r, header) for r in data_rows]
    text = "\n\n".join(line for line in lines if line)

    return ParseResult(
        text=text,
        page_count=None,
        extra={
            "row_count": len(data_rows),
            "columns": header or [],
            "has_header": has_header,
            "delimiter": getattr(dialect, "delimiter", ","),
        },
    )
