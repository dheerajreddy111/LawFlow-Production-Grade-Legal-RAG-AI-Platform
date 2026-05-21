"""
Deterministic retrieval reranking for LawFlow RAG.

Vector similarity over a dense legal corpus is too broad: for "can I drink
and drive?", §185 (drunk driving) and §3 (driving licence) score almost
identically in cosine space. This stage re-scores the top-k vector hits
with cheap, explainable legal signals and keeps only the 1–3 strongest,
suppressing semantically-adjacent but legally-irrelevant provisions.

Lightweight by design — no cross-encoder. Pure, synchronous, sub-millisecond
for ≤10 short chunks (safe to call inside the async pipeline). Reuses the
act-registry's topic intelligence rather than duplicating a keyword list.

Signals (blended, weights below)
    similarity      vector cosine score (recall anchor)
    topic overlap   how many query legal-topic terms occur in the chunk
                    (the dominant separator: "under influence" hits §185,
                    not §3/§129)
    term density    share of query content words present in the chunk
    act / domain    chunk's act-key / domain matches the query's topic acts
    section align   query cites a number that equals the chunk's number

Explainability: every kept chunk gets ``rerank_score`` and a terse
``rerank_reason`` set on it — internal only, for the future transparency
panel. The response schema is unchanged.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from app.integrations.lc import traced
from app.services.act_registry import (
    domain_for,
    expand_topics,
    resolve_act,
    topic_acts,
)

# ── Tunables ──────────────────────────────────────────────────────────────────

RAG_RETRIEVE_K: int = int(os.getenv("RAG_RETRIEVE_K", "10"))
RAG_RERANK_KEEP: int = int(os.getenv("RAG_RERANK_KEEP", "3"))
# A secondary provision is kept only if its rerank score is at least this
# fraction of the primary's — this is what makes "related provisions"
# appear only when genuinely on-point.
RAG_RERANK_REL: float = float(os.getenv("RAG_RERANK_REL", "0.78"))
# Hard floor: nothing below this rerank score survives (except the primary,
# so a grounded answer is always possible).
RAG_RERANK_FLOOR: float = float(os.getenv("RAG_RERANK_FLOOR", "0.18"))

# Signal weights — topic overlap dominates; similarity anchors recall.
_W_SIM, _W_TOPIC, _W_DENSITY, _W_ACT, _W_SEC = 0.28, 0.42, 0.14, 0.10, 0.06

_STOP = frozenset(
    "a an the of to in on at by for with is are was were be been can could "
    "may might shall should will would do does did i we you he she it they "
    "what which who whom how when where why and or not no any my our your "
    "this that these those if then under as about into from".split()
)
_WORD = re.compile(r"[a-z]+")
_SEC_NUM = re.compile(r"\b(\d{1,4}[a-z]?)\b", re.I)


@dataclass
class _Scored:
    score: float
    reason: str


def _content_tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def _score_chunk(query: str, chunk) -> _Scored:  # chunk: RetrievedChunk
    q_low = query.lower()
    text_low = chunk.text.lower()
    meta = chunk.metadata or {}

    sim = max(0.0, min(1.0, float(chunk.score)))

    # Topic overlap — the decisive legal-relevance signal.
    topic_terms = expand_topics(query)
    topic_hits = sum(1 for t in topic_terms if t.lower() in text_low)
    topic = min(topic_hits, 3) / 3.0

    # Query-term density (stemmed: first 4 chars) in the chunk.
    q_tokens = _content_tokens(query)
    if q_tokens:
        present = sum(1 for w in q_tokens if w[:4] in text_low)
        density = present / len(q_tokens)
    else:
        density = 0.0

    # Act / domain consistency.
    want_acts = set(topic_acts(query))
    for w in _WORD.findall(q_low):
        k = resolve_act(w)
        if k:
            want_acts.add(k)
    chunk_act = str(meta.get("extra.act_key") or "")
    act = 1.0 if chunk_act and chunk_act in want_acts else 0.0
    if not act and want_acts:
        want_domains = {domain_for(k) for k in want_acts}
        if str(meta.get("extra.domain") or "") in want_domains:
            act = 0.5

    # Section-number alignment (matters for "what about 185?").
    chunk_num = str(meta.get("extra.number") or "").lower()
    q_nums = {m.group(1).lower() for m in _SEC_NUM.finditer(q_low)}
    sec = 1.0 if chunk_num and chunk_num in q_nums else 0.0

    total = (
        _W_SIM * sim
        + _W_TOPIC * topic
        + _W_DENSITY * density
        + _W_ACT * act
        + _W_SEC * sec
    )
    reason = (
        f"sim={sim:.2f} topic={topic_hits} dens={density:.2f} "
        f"act={chunk_act or '-'}({act:g}) sec={sec:g}"
    )
    return _Scored(round(total, 4), reason)


@traced(name="rag.rerank", run_type="tool")
def rerank(query: str, chunks: list) -> list:
    """Re-score vector hits and keep the 1–3 strongest.

    Returns chunks ordered primary-first with ``rerank_score`` /
    ``rerank_reason`` populated. The primary is always kept; secondary
    provisions only if they clear the relative band *and* the floor.
    """
    if not chunks:
        return []

    scored = []
    for c in chunks:
        s = _score_chunk(query, c)
        c.rerank_score = s.score
        c.rerank_reason = s.reason
        scored.append(c)

    scored.sort(key=lambda c: c.rerank_score, reverse=True)

    primary = scored[0]
    primary.rerank_reason = f"primary | {primary.rerank_reason}"
    kept = [primary]
    top = primary.rerank_score or 1e-9
    for c in scored[1 : RAG_RERANK_KEEP]:
        if (
            c.rerank_score >= RAG_RERANK_FLOOR
            and c.rerank_score >= RAG_RERANK_REL * top
        ):
            c.rerank_reason = f"related | {c.rerank_reason}"
            kept.append(c)
    return kept
