"""Query rewriting + variant generation for retrieval.

Two stages, both deterministic and cheap (no LLM round-trip):

1. **Rewrite** — produce an "expanded" form of the user query that has
   stronger lexical signal for retrieval. For "Can I get bail?" we
   inject the act names and statutory terms from the topic registry to
   produce "Can I get bail bail anticipatory bail pre-arrest bail under
   Code of Criminal Procedure". The original query is still passed to
   the LLM in the prompt; only the retrieval substrate sees the
   expanded form.

2. **Variants** — generate up to N alternative phrasings of the query
   (original, expanded, section-number-anchored when applicable). The
   multi-query retriever uses these to widen recall without sacrificing
   precision; each variant retrieves independently and the lists are
   fused via RRF.

Why deterministic and not LLM-driven
------------------------------------
LLM query rewriting is great when the corpus is large and diverse, but
it adds latency (a full round-trip) on every query and introduces a
stochastic element to retrieval. For a curated legal corpus the
topic-synonym registry we already maintain (see
:mod:`app.services.act_registry`) is a far better source — it knows
which terms mean the same thing inside Indian law. We keep the door
open for an LLM rewriter via the ``llm_rewriter`` hook, but the default
is the deterministic pass.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable

from app.integrations.lc import traced
from app.services.act_registry import (
    ACT_REGISTRY,
    expand_topics,
    resolve_act,
    topic_acts,
)

logger = logging.getLogger(__name__)


# Section-number anchor — "section 25F", "art 21", "§185", "302 IPC".
_SECTION_NUMBER = re.compile(
    r"(?:(?:section|sec|s\.|article|art\.|art|§)\s*)?(\d{1,4}[a-z]?)",
    re.IGNORECASE,
)
_WORD = re.compile(r"[a-zA-Z]+")
_STOP = frozenset(
    "a an the of to in on at by for with is are was were be been can could "
    "may might shall should will would do does did i we you he she it they".split()
)


# ── Output type ───────────────────────────────────────────────────────────────


@dataclass
class RewrittenQuery:
    """A bundle of query variants to drive multi-query retrieval.

    ``original`` is the user-typed string; ``expanded`` is the
    deterministic-synonym form; ``variants`` is the deduplicated list of
    every phrasing the retriever should try. ``act_keys`` and
    ``sections`` are the metadata hints the retriever uses to build
    Chroma ``where`` filters.
    """

    original: str
    expanded: str
    variants: list[str] = field(default_factory=list)
    act_keys: list[str] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────────


def detect_act_keys(text: str) -> list[str]:
    """Return canonical act keys mentioned in ``text``, plus topic-inferred ones.

    Words like "IPC", "CrPC", "Article 21 of the Constitution" resolve
    directly; topical queries ("bail", "drunk driving") expand through
    :func:`topic_acts` so the metadata filter still narrows correctly.
    """
    seen: list[str] = []
    # 1. Direct alias hits — both single tokens ("ipc") and the full
    # text ("under the Indian Penal Code, 1860").
    for token in [text, *_WORD.findall(text)]:
        key = resolve_act(token)
        if key and key not in seen:
            seen.append(key)
    # 2. Topical inference.
    for key in topic_acts(text):
        if key not in seen:
            seen.append(key)
    return seen


def detect_section_numbers(text: str) -> list[str]:
    """Return any section / article numbers cited in ``text`` (lowercase).

    Strips the "section" / "article" / "§" prefix so the returned token
    matches the ``extra.number`` field on chunk metadata.
    """
    out: list[str] = []
    for m in _SECTION_NUMBER.finditer(text):
        n = m.group(1).lower()
        if n and n not in out:
            out.append(n)
    return out


@traced(name="rag.query_rewrite", run_type="tool")
def rewrite_query(
    query: str,
    *,
    llm_rewriter: Callable[[str], str] | None = None,
) -> RewrittenQuery:
    """Produce an expanded form of the query plus retrieval-time variants.

    The expansion appends topic-synonym terms and any resolved act
    names; the LLM is only invoked when ``llm_rewriter`` is passed.
    """
    q = (query or "").strip()
    if not q:
        return RewrittenQuery(original="", expanded="", variants=[])

    topics = expand_topics(q)
    acts = detect_act_keys(q)
    sections = detect_section_numbers(q)

    # Build the expansion. Order: original text, then deduplicated
    # synonym terms, then act display names. The bi-encoder + BM25 both
    # consume this as a bag-of-words at retrieval time.
    pieces: list[str] = [q]
    seen: set[str] = set(_WORD.findall(q.lower()))
    for term in topics:
        low = term.lower()
        if low not in seen:
            pieces.append(term)
            seen.update(_WORD.findall(low))
    for k in acts:
        name = ACT_REGISTRY[k].name if k in ACT_REGISTRY else k
        low = name.lower()
        if low not in seen:
            pieces.append(name)
            seen.update(_WORD.findall(low))

    expanded = " ".join(pieces)

    variants: list[str] = []
    variants.append(q)
    if expanded != q:
        variants.append(expanded)
    # When the user cited a specific section, add a variant that
    # foregrounds the section number — this nudges BM25 to surface
    # exact matches even when the topical wording is generic.
    if sections and acts:
        anchor = " ".join(
            f"section {n} {ACT_REGISTRY[k].name}"
            for n in sections[:2]
            for k in acts[:1]
            if k in ACT_REGISTRY
        )
        if anchor and anchor not in variants:
            variants.append(anchor)
    # Optional LLM rewrite — last so deterministic variants dominate
    # when the LLM fails or produces a garbage result.
    if llm_rewriter is not None:
        try:
            rewrite = (llm_rewriter(q) or "").strip()
            if rewrite and rewrite not in variants:
                variants.append(rewrite)
        except Exception:  # noqa: BLE001 — boundary: LLM mishap shouldn't break retrieval
            logger.exception("LLM query rewriter raised; falling back")

    # Cap variants to keep multi-query retrieval bounded.
    return RewrittenQuery(
        original=q,
        expanded=expanded,
        variants=variants[:4],
        act_keys=acts,
        sections=sections,
    )


def build_metadata_filter(
    act_keys: list[str],
    *,
    jurisdiction: str | None = None,
) -> dict | None:
    """Translate detected metadata into a Chroma ``where`` clause.

    When ``act_keys`` is non-empty the filter narrows retrieval to
    those acts. We OR the keys (``$in``) rather than AND them — a query
    that names "IPC and BNS" should see hits from either.

    Returns ``None`` when there's nothing to filter on; the caller
    should NOT pass a falsy filter to Chroma (it would 400).
    """
    clauses: list[dict] = []
    if act_keys:
        if len(act_keys) == 1:
            clauses.append({"extra.act_key": act_keys[0]})
        else:
            clauses.append({"extra.act_key": {"$in": list(act_keys)}})
    if jurisdiction:
        clauses.append({"extra.jurisdiction": jurisdiction})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


__all__ = [
    "RewrittenQuery",
    "build_metadata_filter",
    "detect_act_keys",
    "detect_section_numbers",
    "rewrite_query",
]
