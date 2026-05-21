"""BM25 + RRF fusion regressions.

The BM25 index is exercised via small in-memory fixtures rather than the
full Chroma store — we want the unit test to pass without the embedding
model being downloaded. The fusion / RRF math is also covered here so a
weight change can't silently break it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.rag.bm25 import BM25Hit, tokenize
from app.rag.hybrid import reciprocal_rank_fusion, rrf_merge_lists
from app.rag.vector_store import SearchResult


def test_tokeniser_keeps_section_numbers_together():
    """`25F` should be a single token, not split into `25` + `F`."""
    toks = tokenize("Section 25F of the Industrial Disputes Act, 1947")
    assert "25f" in toks
    assert "industrial" in toks
    # Stopwords gone.
    assert "the" not in toks
    assert "of" not in toks


def test_tokeniser_keeps_section_marker():
    toks = tokenize("§185 drunk driving")
    assert "§" in toks
    assert "185" in toks
    assert "drunk" in toks


# ── RRF math ────────────────────────────────────────────────────────────────


def _vec(cid: str) -> SearchResult:
    return SearchResult(
        chunk_id=cid, text="t", score=1.0, source="s", metadata={}
    )


def _bm(cid: str, sc: float = 1.0) -> BM25Hit:
    return BM25Hit(chunk_id=cid, text="t", score=sc, source="s", metadata={})


def test_rrf_chunk_in_both_ranks_higher():
    """A chunk in both retrievers should outrank a chunk in only one."""
    fused = reciprocal_rank_fusion(
        [_vec("A"), _vec("B"), _vec("C")],
        [_bm("B"), _bm("D")],
    )
    by_id = {f.chunk_id: f for f in fused}
    # B is in both → score == 1/61 + 1/61 (rank 2 vec + rank 1 bm25)
    # A is in vector only at rank 1.
    assert by_id["B"].score > by_id["A"].score
    assert by_id["B"].contributions == {"vector": 2, "bm25": 1}


def test_rrf_weights_skew_results():
    """A 2.0 vector weight should let a vector-only hit beat a tied bm25 hit."""
    fused_balanced = reciprocal_rank_fusion(
        [_vec("A")], [_bm("B")],
        weights={"vector": 1.0, "bm25": 1.0},
    )
    by_id_balanced = {f.chunk_id: f for f in fused_balanced}
    # Both at rank 1 → equal scores
    assert pytest.approx(by_id_balanced["A"].score, rel=1e-6) == by_id_balanced["B"].score

    fused_skewed = reciprocal_rank_fusion(
        [_vec("A")], [_bm("B")],
        weights={"vector": 2.0, "bm25": 1.0},
    )
    by_id_skewed = {f.chunk_id: f for f in fused_skewed}
    assert by_id_skewed["A"].score > by_id_skewed["B"].score


def test_rrf_orders_by_score_desc():
    fused = reciprocal_rank_fusion(
        [_vec("A"), _vec("B")], [_bm("C"), _bm("D")]
    )
    scores = [f.score for f in fused]
    assert scores == sorted(scores, reverse=True)


# ── Multi-list RRF (multi-query retrieval) ──────────────────────────────────


@dataclass
class _Hit:
    chunk_id: str
    text: str = ""


def test_rrf_merge_lists_fuses_variants():
    list_a = [_Hit("X"), _Hit("Y"), _Hit("Z")]
    list_b = [_Hit("Y"), _Hit("W"), _Hit("X")]
    merged = rrf_merge_lists([list_a, list_b])
    ids = [m.chunk_id for m in merged]
    # X and Y appear in both → should be ahead of W (only in B) and Z (only in A).
    assert ids[0] in {"X", "Y"}
    assert ids[1] in {"X", "Y"}
    assert set(ids[:2]) == {"X", "Y"}
