"""Structured output schemas + the citation-validator tool.

This module provides:

- :class:`CitationReport` — Pydantic schema describing which ``[n]``
  markers appear in a generated answer and whether each one points to
  a real retrieved chunk.
- :func:`validate_citations` — pure-Python (no LLM) implementation that
  produces the report from ``(answer, retrieved_chunks)``.
- :func:`citation_validator_tool` — the same logic surfaced as a
  LangChain :class:`Tool` so it can be invoked by the LangGraph RAG
  graph (or by future agents) under a single, traced name.

Why no LLM?
-----------
A model that grades its own citations is unreliable and would double
the latency of the RAG path. The check is structural: parse ``[n]``
markers, compare against the count of retrieved chunks, flag the
mismatches. The graph uses this report to drop hallucinated citations
before the answer is returned, never adding LLM cost.
"""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


class CitationReport(BaseModel):
    """Structural validation of ``[n]`` citation markers in an answer."""

    cited_indices: list[int] = Field(
        default_factory=list,
        description="1-based citation indices that appear in the answer "
        "(deduplicated, preserving first-mention order).",
    )
    valid_indices: list[int] = Field(
        default_factory=list,
        description="Subset of ``cited_indices`` that map to a real "
        "retrieved chunk (i.e. ``1 ≤ i ≤ n_chunks``).",
    )
    missing_indices: list[int] = Field(
        default_factory=list,
        description="Citations the model emitted but no chunk exists for "
        "(e.g. ``[7]`` when only 3 chunks were retrieved).",
    )
    n_chunks: int = Field(
        default=0,
        description="Number of retrieved chunks the answer was grounded in.",
    )
    all_valid: bool = Field(
        default=True,
        description="True iff every cited index maps to a retrieved chunk.",
    )
    any_citation: bool = Field(
        default=False,
        description="True iff at least one ``[n]`` marker is present.",
    )

    def usable_indices(self) -> list[int]:
        """Indices safe to surface to the UI as sources, in citation order."""
        return list(self.valid_indices)


def validate_citations(answer: str, n_chunks: int) -> CitationReport:
    """Structurally check the ``[n]`` markers in an answer.

    Parameters
    ----------
    answer
        The model's generated string (markdown is fine).
    n_chunks
        Number of retrieved chunks the prompt was assembled from.

    Returns
    -------
    CitationReport
        Structural breakdown; never raises.
    """
    cited: list[int] = []
    seen: set[int] = set()
    for m in _CITATION_RE.finditer(answer or ""):
        try:
            idx = int(m.group(1))
        except ValueError:
            continue
        if idx in seen:
            continue
        seen.add(idx)
        cited.append(idx)

    valid: list[int] = [i for i in cited if 1 <= i <= max(n_chunks, 0)]
    missing: list[int] = [i for i in cited if i not in set(valid)]

    return CitationReport(
        cited_indices=cited,
        valid_indices=valid,
        missing_indices=missing,
        n_chunks=int(n_chunks),
        all_valid=(not missing) and (not cited or bool(valid)),
        any_citation=bool(cited),
    )


# ── LangChain tool wrapper ────────────────────────────────────────────────────

@tool("citation_validator", return_direct=False)
def citation_validator_tool(
    answer: str,
    n_chunks: int,
) -> dict[str, Any]:
    """Validate citation markers in a RAG-generated answer.

    Inputs:
        answer    — model output containing ``[n]`` markers.
        n_chunks  — number of retrieved chunks the answer is grounded in.

    Returns a JSON-serialisable CitationReport (see schema).
    """
    return validate_citations(answer, n_chunks).model_dump()
