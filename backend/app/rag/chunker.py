"""
Legal document chunking service for LawFlow.

Splits a plain-text document into overlapping chunks that respect semantic
boundaries — paragraph breaks and section headings — rather than cutting at
arbitrary character offsets.

Two segmentation strategies (auto-selected by default):

    paragraph  – split at double-newline boundaries; best for unstructured
                 prose, witness statements, and running text.
    section    – detect legal section / chapter / article headings and split
                 there; best for statutes, structured contracts, and
                 court orders.

Both strategies apply a greedy sliding-window with configurable overlap so
no context is lost at chunk boundaries.  This is critical for vector search:
a query embedding may match text that straddles two adjacent chunks.

Chunk IDs are deterministic (SHA-256 of source + index + first 200 chars)
so the same document always produces the same IDs, enabling idempotent
upserts into any vector store.

Embedding integration hook
--------------------------
ChunkMetadata includes an `embedding_id` field (None until populated) and an
`extra` pass-through dict.  When the embedding service is added:
    1. Call DocumentChunker.chunk() to get list[DocumentChunk].
    2. Batch-embed chunk.text for each chunk.
    3. Store the vector-store ID in chunk.metadata.embedding_id.
    4. Upsert the full ChunkMetadata as vector-store payload.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, Field

# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChunkConfig:
    """Immutable chunking parameters passed to DocumentChunker.

    The default targets an 800-char window with 150-char overlap — the
    sweet spot the retrieval team converged on after benchmarking. The
    previous 1000 / 200 default fired too many cross-section overlaps
    that polluted top-k for narrow legal queries.
    """
    max_chars: int                                        = 800
    overlap:   int                                        = 150
    strategy:  Literal["auto", "paragraph", "section"]   = "auto"
    min_chars: int                                        = 50   # drop orphan micro-chunks
    # Soft floor — when a sentence-boundary split would leave the trailing
    # piece below this, fold it back into the previous chunk rather than
    # emit a sliver. Keeps BM25 idf statistics from being dominated by
    # 30-char fragments.
    fold_below: int                                       = 200


# ── Public output types ───────────────────────────────────────────────────────

class ChunkMetadata(BaseModel):
    # Provenance
    source:        str
    chunk_index:   int
    total_chunks:  int
    strategy:      str            # "paragraph" | "section" (resolved, never "auto")

    # Position in original document
    start_char:    int
    end_char:      int

    # Semantic context
    section_title: str | None = None   # nearest enclosing heading, if detected

    # Embedding hook — populated by the embedding service in the RAG phase
    embedding_id:  str | None = None

    # Document versioning — populated by app.rag.versioning. Defaults make
    # newly-chunked documents "version 1, active" without any caller
    # changes; the version-aware ingest path overwrites these as needed.
    version_id:    str | None = None   # content hash of the source revision
    version:       int        = 1       # 1-based revision number for this source
    superseded:    bool       = False   # True once a newer revision exists
    ingested_at:   str | None = None    # ISO-8601 UTC; set by the ingest helper

    # Pass-through from IngestResult.metadata (page_count, content_type, …)
    extra:         dict[str, object] = Field(default_factory=dict)


class DocumentChunk(BaseModel):
    chunk_id: str           # deterministic 16-char hex ID
    text:     str
    metadata: ChunkMetadata


# ── Internal structures ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Segment:
    """A contiguous slice of the original document text."""
    text:    str
    start:   int             # char offset in the original text
    end:     int             # exclusive end char offset
    heading: str | None = None  # section heading this segment belongs to


@dataclass
class _RawChunk:
    text:          str
    start_char:    int
    end_char:      int
    section_title: str | None


# ── Section-header detection ──────────────────────────────────────────────────
# Covers the most common Indian legal document heading patterns.

_NUMBERED_HEADING = re.compile(r'^\d+(?:\.\d+)*\.?\s+[A-Z]')
_ROMAN_HEADING    = re.compile(r'^(?=[MDCLXVI])M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})\.\s+[A-Z]')
_KEYWORD_HEADING  = re.compile(
    r'^(?:CHAPTER|PART|SCHEDULE|ANNEXURE|APPENDIX|TITLE|BOOK)\s+(?:\d+|[IVXLC]+|[A-Z])\b', re.I
)
# Statute / contract structural markers — "Section 25F", "Article 21",
# "Clause 7", "§5". These don't have to be all-caps; they're a strong
# structural signal that survives mixed-case bodies. The whitespace is
# optional after `§` (commonly written as "§185" with no space).
_LEGAL_UNIT_HEADING = re.compile(
    r'^(?:(?:section|article|clause|rule|order|regulation|provision)\s+|§\s*)'
    r'\d+[A-Za-z]?(?:\([0-9a-z]+\))?(?:\s*[—\-:.])?',
    re.I,
)
# Sub-clause markers like "(1)", "(a)", "(iv)" at the start of a line.
# These are NOT treated as section breaks (too fine-grained) but the
# segmenter prefers to split before them when the parent is oversized.
_SUBCLAUSE_MARKER = re.compile(r'^\(\s*(?:\d+|[a-z]|[ivxlc]+)\s*\)\s+')


def _is_section_header(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 120:
        return False
    # 1. "1.", "1.1", "2.3.4." followed by an uppercase word
    if _NUMBERED_HEADING.match(s):
        return True
    # 2. "I.", "IV.", "XII." followed by uppercase
    if _ROMAN_HEADING.match(s):
        return True
    # 3. CHAPTER I, PART 2, SCHEDULE III, ANNEXURE B, TITLE II
    if _KEYWORD_HEADING.match(s):
        return True
    # 4. Section 25F, Article 21, Clause 7, §5 — structural markers
    #    common in statutes / contracts. These do NOT require uppercase
    #    bodies and are the strongest signal we have for legal documents.
    if _LEGAL_UNIT_HEADING.match(s):
        return True
    # 5. All-caps heading: 5–80 chars, alpha + spaces + hyphens, no sentence punctuation
    if (
        5 <= len(s) <= 80
        and s == s.upper()
        and re.search(r'[A-Z]', s)
        and not re.search(r'[.!?,;]', s)
    ):
        return True
    return False


def _has_sections(text: str) -> bool:
    """True when ≥ 2 lines look like section headings."""
    found = 0
    for line in text.splitlines():
        if _is_section_header(line):
            found += 1
            if found >= 2:
                return True
    return False


# ── Segmenters ────────────────────────────────────────────────────────────────

def _paragraphs(text: str) -> list[_Segment]:
    """
    Split on blank lines (two or more consecutive newlines).
    Uses re.split with a capturing group to walk through the original
    string without losing char offsets.
    """
    segments: list[_Segment] = []
    pos = 0
    for piece in re.split(r'(\n{2,})', text):
        if re.fullmatch(r'\n+', piece):
            pos += len(piece)
            continue
        stripped = piece.strip()
        if not stripped:
            pos += len(piece)
            continue
        # Locate the stripped content inside this piece (skips leading whitespace)
        leading = piece.find(stripped[0])
        leading = max(leading, 0)
        start   = pos + leading
        end     = start + len(stripped)
        segments.append(_Segment(text=stripped, start=start, end=end))
        pos += len(piece)
    return segments


def _sections(text: str) -> list[_Segment]:
    """
    Split the document at detected section headings.
    Each section runs from its heading to the line before the next heading.
    """
    lines   = text.splitlines(keepends=True)
    offsets: list[int] = []
    cur = 0
    for ln in lines:
        offsets.append(cur)
        cur += len(ln)
    offsets.append(cur)  # sentinel: len(text)

    # Collect line indices where a new section starts
    breaks = [0]
    for i, ln in enumerate(lines):
        if i > 0 and _is_section_header(ln.rstrip('\n\r')):
            breaks.append(i)
    breaks.append(len(lines))

    segments: list[_Segment] = []
    for lo, hi in zip(breaks, breaks[1:]):
        char_start = offsets[lo]
        char_end   = offsets[hi]
        raw        = text[char_start:char_end]
        content    = raw.strip()
        if not content:
            continue
        first_line  = content.split('\n')[0].strip()
        heading     = first_line if _is_section_header(first_line) else None
        leading     = raw.find(content[0])
        leading     = max(leading, 0)
        abs_start   = char_start + leading
        segments.append(_Segment(
            text=content,
            start=abs_start,
            end=abs_start + len(content),
            heading=heading,
        ))
    return segments


# ── Oversized segment splitting ───────────────────────────────────────────────

# Sentence boundary: punctuation (.!?) followed by one or more whitespace chars.
# The match covers the whitespace between sentences so each split piece
# retains the original text with correct whitespace.
_SENTENCE_END: Final[re.Pattern[str]] = re.compile(r'(?<=[.!?])\s+')


def _sentence_split(text: str, max_chars: int, *, fold_below: int = 0) -> list[str]:
    """
    Greedy sentence-boundary split: accumulate sentences until the next one
    would exceed max_chars, then emit and start a new chunk.
    Falls back to sub-clause splits, then word-boundary splitting.

    ``fold_below`` collapses a tiny trailing piece into its predecessor so
    we never emit ten-word slivers that pollute IDF stats and confuse
    cosine retrieval.
    """
    # Build a list of sentence strings that together reconstruct the original text
    positions = [0] + [m.end() for m in _SENTENCE_END.finditer(text)] + [len(text)]
    sentences = [text[a:b] for a, b in zip(positions, positions[1:]) if text[a:b].strip()]

    if len(sentences) <= 1:
        # No sentence breaks — try sub-clause markers before falling back
        # to a hard word split. Helps long single-sentence statutory
        # provisions ("Whoever … (1) X (2) Y (3) Z.") split cleanly.
        sub = _subclause_split(text, max_chars)
        if len(sub) > 1:
            return sub
        return _word_split(text, max_chars)

    result:     list[str] = []
    buf_start   = 0
    buf_len     = 0

    for i, sent in enumerate(sentences):
        if buf_len + len(sent) > max_chars and buf_len > 0:
            result.append("".join(sentences[buf_start:i]).strip())
            buf_start = i
            buf_len   = len(sent)
        else:
            buf_len += len(sent)

    if buf_start < len(sentences):
        result.append("".join(sentences[buf_start:]).strip())

    pieces = [r for r in result if r] or [text]

    # If any piece is still oversized after sentence-greedy aggregation
    # (a single very long sentence — common in legacy statutes with
    # serial sub-clauses), recurse into a sub-clause split for that
    # piece. The result is flattened back into the pieces list.
    expanded: list[str] = []
    for p in pieces:
        if len(p) > max_chars:
            sub = _subclause_split(p, max_chars)
            if len(sub) > 1:
                expanded.extend(sub)
                continue
        expanded.append(p)
    pieces = expanded

    # Fold a tiny tail into its predecessor so we never emit slivers.
    # The threshold is capped at one quarter of max_chars so a small
    # ``fold_below`` setting doesn't accidentally collapse two roughly-
    # equal pieces (e.g. 155 + 186 with fold_below=200) — those aren't
    # slivers and the cost of merging them is an oversized chunk.
    threshold = min(fold_below, max(0, max_chars // 4))
    if (
        threshold > 0
        and len(pieces) >= 2
        and len(pieces[-1]) < threshold
        and len(pieces[-2]) + len(pieces[-1]) <= max_chars + threshold
    ):
        merged = (pieces[-2].rstrip() + " " + pieces[-1].lstrip()).strip()
        pieces = pieces[:-2] + [merged]

    return pieces


def _subclause_split(text: str, max_chars: int) -> list[str]:
    """Split before each '(1)', '(a)', '(iv)' marker.

    Useful for long single-sentence statutory provisions that bundle a
    list of sub-clauses without sentence punctuation. Returns the
    original text as a single element when no markers are found, so the
    caller's fallback chain continues unchanged.
    """
    # Match the marker at the start of a line OR after meaningful whitespace.
    pattern = re.compile(r'(?:(?<=\n)|(?<=\s))\(\s*(?:\d+|[a-z]|[ivxlc]+)\s*\)\s+')
    cuts = [m.start() for m in pattern.finditer(text)]
    if not cuts:
        return [text]
    # Always include the head as a piece.
    bounds = [0, *cuts, len(text)]
    pieces = [text[a:b].strip() for a, b in zip(bounds, bounds[1:])]
    pieces = [p for p in pieces if p]

    # Greedy re-aggregation under max_chars — preserves the structure but
    # avoids one chunk per sub-clause when they're tiny.
    out: list[str] = []
    buf = ""
    for p in pieces:
        if buf and len(buf) + 1 + len(p) > max_chars:
            out.append(buf)
            buf = p
        else:
            buf = (buf + " " + p).lstrip() if buf else p
    if buf:
        out.append(buf)
    return out or [text]


def _word_split(text: str, max_chars: int) -> list[str]:
    """Last-resort word-boundary split for text with no sentence markers."""
    result: list[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > max_chars:
            result.append(current)
            current = word
        else:
            current = (current + " " + word).lstrip() if current else word
    if current:
        result.append(current)
    return result or [text]


def _expand(
    segs: list[_Segment],
    max_chars: int,
    *,
    fold_below: int = 0,
) -> list[_Segment]:
    """
    Replace any segment longer than max_chars with sub-segments split at
    sentence (then sub-clause, then word) boundaries.  Sub-segments
    inherit the parent's section heading so metadata stays correct.
    """
    result: list[_Segment] = []
    for seg in segs:
        if len(seg.text) <= max_chars:
            result.append(seg)
            continue
        parts  = _sentence_split(seg.text, max_chars, fold_below=fold_below)
        cursor = 0
        for part in parts:
            idx = seg.text.find(part, cursor)
            idx = max(idx, cursor) if idx != -1 else cursor
            abs_start = seg.start + idx
            result.append(_Segment(
                text=part,
                start=abs_start,
                end=abs_start + len(part),
                heading=seg.heading,
            ))
            cursor = idx + len(part)
    return result


# ── Sliding window ────────────────────────────────────────────────────────────

def _window(
    segs:      list[_Segment],
    max_chars: int,
    overlap:   int,
) -> list[_RawChunk]:
    """
    Greedy sliding-window chunking over a list of segments.

    Algorithm:
        1. Accumulate segments from `start` until adding the next one would
           exceed max_chars.
        2. Emit the accumulated window as a chunk.
        3. Slide `start` backward until the trailing segments sum to at least
           `overlap` chars — these segments are included again at the head of
           the next chunk, giving consumers overlapping context.
        4. Repeat from step 1.

    A segment that alone exceeds max_chars is emitted as-is (never skipped).
    """
    if not segs:
        return []

    chunks: list[_RawChunk] = []
    start = 0

    while start < len(segs):
        end  = start
        size = 0

        # Greedily accumulate
        while end < len(segs):
            next_size = size + len(segs[end].text)
            if next_size > max_chars and end > start:
                break        # would overflow; stop before this segment
            size = next_size
            end += 1

        if end == start:     # single segment exceeds max_chars → emit anyway
            end = start + 1

        window        = segs[start:end]
        chunk_text    = "\n\n".join(s.text for s in window)
        section_title = next((s.heading for s in window if s.heading), None)

        chunks.append(_RawChunk(
            text=chunk_text,
            start_char=window[0].start,
            end_char=window[-1].end,
            section_title=section_title,
        ))

        if end >= len(segs):
            break

        # Slide backward by overlap: walk back from end-1, stopping no further
        # than start+1 so `start` always advances and the outer loop terminates.
        # (If overlap >= entire window size the full backward walk would set
        # new_start = start, causing an infinite loop.)
        acc       = 0
        new_start = end           # default: no overlap
        for i in range(end - 1, start, -1):   # range stops at start+1
            acc      += len(segs[i].text)
            new_start = i
            if acc >= overlap:
                break

        start = new_start         # guaranteed >= start + 1

    return chunks


# ── Chunk ID generation ───────────────────────────────────────────────────────

def _make_id(source: str, index: int, text: str) -> str:
    """
    Deterministic 16-char hex ID (64-bit collision space).
    Includes source, index, and the first 200 chars of content so the same
    document always produces the same IDs — safe for idempotent vector upserts.
    """
    payload = f"{source}\x00{index}\x00{text[:200]}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── Public chunker ────────────────────────────────────────────────────────────

class DocumentChunker:
    """
    Semantic-aware legal document chunker.

    Stateless after construction; safe to share across async tasks.

    Args:
        config: ChunkConfig instance controlling size, overlap, and strategy.

    Example::

        chunker = DocumentChunker(ChunkConfig(max_chars=800, overlap=150))
        chunks  = await chunker.chunk(
            text   = extracted_text,
            source = "judgment_2024.pdf",
            extra  = {"page_count": 12, "content_type": "application/pdf"},
        )
    """

    def __init__(self, config: ChunkConfig = ChunkConfig()) -> None:
        self._cfg = config

    async def chunk(
        self,
        text:   str,
        source: str,
        extra:  dict[str, object] | None = None,
    ) -> list[DocumentChunk]:
        """Async entry point. CPU-bound work is dispatched to a thread pool."""
        return await asyncio.to_thread(
            self._chunk_sync, text, source, extra or {}
        )

    # ── private ──────────────────────────────────────────────────────────────

    def _chunk_sync(
        self,
        text:   str,
        source: str,
        extra:  dict[str, object],
    ) -> list[DocumentChunk]:
        text = text.strip()
        if not text:
            return []

        cfg = self._cfg

        # 1. Resolve strategy
        strategy: str = cfg.strategy
        if strategy == "auto":
            strategy = "section" if _has_sections(text) else "paragraph"

        # 2. Segment the document
        segs: list[_Segment] = (
            _sections(text) if strategy == "section" else _paragraphs(text)
        )

        # 3. Expand any segment that alone exceeds max_chars
        segs = _expand(segs, cfg.max_chars, fold_below=cfg.fold_below)

        # 4. Drop micro-chunks below min_chars
        segs = [s for s in segs if len(s.text) >= cfg.min_chars]

        if not segs:
            return []

        # 5. Apply sliding window
        raw   = _window(segs, cfg.max_chars, cfg.overlap)
        total = len(raw)

        # 6. Ingestion observability — strategy + chunk counts + size histogram.
        # Import here so the chunker module stays importable without the
        # services package (used in fixture tests).
        try:
            from app.services.metrics import metrics

            metrics.inc("chunker_documents_total", strategy=strategy)
            metrics.inc("chunker_chunks_total", strategy=strategy, by=total)
            for rc in raw:
                metrics.observe("chunker_chunk_size_chars", float(len(rc.text)))
        except Exception:  # noqa: BLE001 — boundary: telemetry must never break chunking
            pass

        # 7. Assemble DocumentChunk objects
        return [
            DocumentChunk(
                chunk_id=_make_id(source, i, rc.text),
                text=rc.text,
                metadata=ChunkMetadata(
                    source=source,
                    chunk_index=i,
                    total_chunks=total,
                    strategy=strategy,
                    section_title=rc.section_title,
                    start_char=rc.start_char,
                    end_char=rc.end_char,
                    extra=extra,
                ),
            )
            for i, rc in enumerate(raw)
        ]
