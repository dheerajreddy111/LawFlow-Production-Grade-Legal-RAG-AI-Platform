"""Structure-aware chunker regressions.

Locks in the legal-document behaviours the retrieval optimisation pass
added:

- legal-unit headings ("Section 25F", "Article 21") detected as section
  starts even when the body is mixed-case;
- numbered sub-clauses ``(1)`` / ``(a)`` / ``(iv)`` used as cut points
  inside long single-sentence provisions;
- trailing slivers folded back into the previous chunk via
  ``ChunkConfig.fold_below``.
"""

from __future__ import annotations

import asyncio

from app.rag.chunker import ChunkConfig, DocumentChunker, _is_section_header


def test_legal_unit_heading_detected():
    assert _is_section_header("Section 25F. Conditions precedent to retrenchment")
    assert _is_section_header("Article 21 — Protection of life and personal liberty")
    assert _is_section_header("§185 Driving under the influence")
    assert _is_section_header("CLAUSE 7. Indemnity")
    # And: a regular prose sentence is NOT a heading.
    assert not _is_section_header(
        "The employer shall not retrench any workman who has been in continuous service for not less than one year."
    )


def test_subclause_split_breaks_long_provision():
    """Single-sentence provisions with sub-clauses should split sensibly."""
    text = (
        "Section 5. Whoever does any of the following acts is liable: "
        "(a) the first act, which involves some statutory wording that "
        "extends the clause to a non-trivial length; "
        "(b) the second act, equally long and detailed in its description; "
        "(c) the third act, also long enough to push past the max; "
        "(d) the fourth act, similarly verbose to keep the clause long."
    )
    chunker = DocumentChunker(ChunkConfig(max_chars=200, overlap=20))
    chunks = asyncio.new_event_loop().run_until_complete(
        chunker.chunk(text, "test.txt")
    )
    # Multiple chunks — the sub-clause splitter fired.
    assert len(chunks) >= 2
    # No chunk grossly exceeds the cap.
    assert all(len(c.text) <= 260 for c in chunks)
    # Sub-clause markers are honoured: at least one chunk starts at "(b)"
    # or later sub-clause boundary.
    assert any(c.text.lstrip().startswith("(") for c in chunks[1:])


def test_fold_below_collapses_short_tail():
    """A small trailing sliver should fold into the previous chunk."""
    text = (
        "First sentence is long enough to fill the buffer all by itself. "
        "Second sentence is also long enough to be its own chunk. "
        "Tiny tail."
    )
    chunker = DocumentChunker(
        ChunkConfig(max_chars=80, overlap=10, fold_below=40)
    )
    chunks = asyncio.new_event_loop().run_until_complete(
        chunker.chunk(text, "test.txt")
    )
    # The "Tiny tail." sliver should be folded — no chunk should be a
    # bare "Tiny tail." with nothing else.
    for c in chunks:
        assert c.text.strip() != "Tiny tail."
