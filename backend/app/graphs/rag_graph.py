"""LangGraph orchestration for the advanced RAG path.

Graph topology
--------------

::

    START → retrieve → rerank → generate → validate → finalize → END

Nodes
-----

retrieve
    Calls :class:`LawFlowRetriever` (which wraps the existing
    :class:`VectorStore` + embedding service) and stores
    :class:`Document` hits in state.

rerank
    Converts hits to :class:`RetrievedChunk`, runs the existing
    deterministic :func:`rerank`, converts back to ``Document``. The
    primary on-point provision is always preserved.

generate
    Renders the LangChain :data:`rag_prompt` template with the numbered
    context and the user query, invokes the configured LLM, stores the
    answer string in state. Token usage is captured automatically via
    LangSmith callbacks when tracing is enabled.

validate
    Runs :func:`validate_citations` (the citation_validator tool) to
    confirm every ``[n]`` marker in the answer points to a real
    retrieved chunk. Hallucinated citations are dropped at finalize.

finalize
    Picks the cited chunks in citation order (dropping invalid
    indices), computes a retrieval-grounded confidence (mean similarity
    of cited chunks), and returns a :class:`RAGResponse`-compatible
    dict.

Behaviour parity
----------------
The output shape matches what :meth:`RAGEngine.answer` already
returns — same fields, same semantics. The graph is invoked behind an
env flag (``RAG_USE_LANGGRAPH=true``) and the calling service
(``LegalService._rag_answer``) accepts the same downstream contract.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypedDict

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from app.integrations.lc.prompts import (
    eval_rag_prompt,
    format_context,
    rag_prompt,
)
from app.integrations.lc.providers import default_lc_provider
from app.integrations.lc.retriever import (
    _chunk_to_document,
    _document_to_chunk,
    build_retriever,
)
from app.integrations.lc.settings import lc_settings
from app.integrations.lc.structured import (
    CitationReport,
    validate_citations,
)
from app.integrations.lc.tracing import get_callbacks
from app.rag.engine import RetrievedChunk
from app.rag.rerank import RAG_RETRIEVE_K
from app.rag.rerank import rerank as deterministic_rerank

if TYPE_CHECKING:
    from app.rag.engine import LLMProvider

logger = logging.getLogger(__name__)


# ── State ─────────────────────────────────────────────────────────────────────

class RAGGraphState(TypedDict, total=False):
    """Graph-wide state.

    All keys are ``total=False`` so nodes don't need to populate
    everything; missing keys mean "not yet computed".
    """

    query: str
    jurisdiction: str | None
    top_k: int
    # Benchmark-only flag. When True, the generate node swaps to the
    # terse eval prompt and the finalize node skips citation-report
    # parsing (eval answers don't carry [n] markers). Production graph
    # invocations leave this missing (default False).
    evaluation_mode: bool

    # populated by retrieve
    documents: list[Document]

    # populated by rerank
    reranked: list[Document]

    # populated by generate
    answer: str

    # populated by validate
    citation_report: dict[str, Any]  # CitationReport.model_dump()

    # populated by finalize
    cited_chunks: list[RetrievedChunk]
    confidence: float


# ── Nodes ────────────────────────────────────────────────────────────────────

async def _retrieve_node(state: RAGGraphState) -> dict[str, Any]:
    """Vector search using the LawFlow VectorStore via the LangChain adapter."""
    retriever = build_retriever(
        top_k=state.get("top_k", RAG_RETRIEVE_K),
        use_rerank=False,  # graph applies rerank as its own node
        jurisdiction=state.get("jurisdiction"),
    )
    docs: list[Document] = await retriever.ainvoke(state["query"])
    return {"documents": docs}


async def _rerank_node(state: RAGGraphState) -> dict[str, Any]:
    """Run the existing deterministic reranker over the retrieved docs."""
    docs = state.get("documents") or []
    if not docs:
        return {"reranked": []}
    chunks = [_document_to_chunk(d) for d in docs]
    kept = deterministic_rerank(state["query"], chunks)
    return {"reranked": [_chunk_to_document(c) for c in kept]}


async def _generate_node(
    state: RAGGraphState, provider: "LLMProvider"
) -> dict[str, Any]:
    """Render the prompt and invoke the LLM to produce an answer.

    Picks the terse benchmark prompt when ``evaluation_mode`` is set on
    the state — production runs leave the flag missing/False and get
    the standard citation-aware prompt.
    """
    docs = state.get("reranked") or []
    eval_mode = bool(state.get("evaluation_mode"))
    if not docs:
        return {
            "answer": (
                "No relevant provision in the corpus."
                if eval_mode
                else (
                    "I could not find any relevant passages in the legal "
                    "corpus to answer this question."
                )
            )
        }
    prompt = eval_rag_prompt if eval_mode else rag_prompt
    messages = prompt.format_messages(
        context=format_context(docs),
        question=state["query"],
    )
    # Translate the rendered chat messages back into the (system, user)
    # tuple our LLMProvider protocol expects. The template only emits two
    # messages (system + user) so this is unambiguous.
    system = ""
    user = ""
    for msg in messages:
        role = getattr(msg, "type", None) or getattr(msg, "role", None)
        content = getattr(msg, "content", "")
        if role == "system":
            system = content
        else:
            user = content
    answer = await provider.complete(system or "", user or "")
    return {"answer": answer}


def _validate_node(state: RAGGraphState) -> dict[str, Any]:
    """Structurally validate the answer's [n] citation markers.

    Skipped under ``evaluation_mode`` because the eval prompt forbids
    [n] markers — running the validator would always produce an empty
    report, and we'd rather not pay the parse cost.
    """
    if state.get("evaluation_mode"):
        return {"citation_report": {"valid_indices": []}}
    docs = state.get("reranked") or []
    report: CitationReport = validate_citations(
        state.get("answer", ""), n_chunks=len(docs)
    )
    return {"citation_report": report.model_dump()}


def _finalize_node(state: RAGGraphState) -> dict[str, Any]:
    """Pick cited chunks in citation order; drop invalid indices.

    Mirrors :func:`app.rag.engine._cited_chunks` exactly so the graph's
    output is interchangeable with :class:`RAGEngine.answer`'s. In
    ``evaluation_mode`` we surface the top-1 reranked chunk as the
    cited source (the eval answer has no [n] markers to parse).
    """
    docs = state.get("reranked") or []
    eval_mode = bool(state.get("evaluation_mode"))
    report_dict = state.get("citation_report") or {}
    valid_idx: list[int] = report_dict.get("valid_indices") or []

    cited: list[RetrievedChunk] = []
    if eval_mode and docs:
        cited.append(_document_to_chunk(docs[0]))
    elif valid_idx:
        for idx in valid_idx:
            if 1 <= idx <= len(docs):
                cited.append(_document_to_chunk(docs[idx - 1]))
    elif docs:
        # Same fallback semantics as _cited_chunks: when the model
        # produced no parseable citations, surface the single primary so
        # the UI always has at least one source for a grounded answer.
        cited.append(_document_to_chunk(docs[0]))

    confidence = (
        round(sum(c.score for c in cited) / len(cited), 4) if cited else 0.0
    )
    return {
        "cited_chunks": cited,
        "confidence": confidence,
    }


# ── Graph assembly ───────────────────────────────────────────────────────────

def build_rag_graph(provider: "LLMProvider | None" = None):
    """Compile the LangGraph for the advanced RAG path.

    The provider can be injected for testing; in production it defaults
    to :func:`default_lc_provider` so calls go through the LangChain
    wrappers (and are auto-instrumented by LangSmith).
    """
    llm: "LLMProvider" = provider or default_lc_provider()

    async def generate_with_provider(state: RAGGraphState) -> dict[str, Any]:
        return await _generate_node(state, llm)

    graph: StateGraph = StateGraph(RAGGraphState)
    graph.add_node("retrieve", _retrieve_node)
    graph.add_node("rerank", _rerank_node)
    graph.add_node("generate", generate_with_provider)
    graph.add_node("validate", _validate_node)
    graph.add_node("finalize", _finalize_node)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "rerank")
    graph.add_edge("rerank", "generate")
    graph.add_edge("generate", "validate")
    graph.add_edge("validate", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


# Module-level singleton — cheap, no client opens until first ainvoke.
_compiled_graph = None


def get_compiled_graph():
    """Return the process-wide compiled graph (lazy)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_rag_graph()
    return _compiled_graph


# ── Public entry point (RAGEngine.answer-shaped) ─────────────────────────────

from dataclasses import dataclass


@dataclass
class GraphRAGResponse:
    """Same shape as :class:`app.rag.engine.RAGResponse`."""

    answer: str
    sources: list[RetrievedChunk]
    confidence: float


async def graph_answer(
    query: str,
    *,
    top_k: int = RAG_RETRIEVE_K,
    jurisdiction: str | None = None,
    evaluation_mode: bool = False,
) -> GraphRAGResponse:
    """Run the LangGraph RAG pipeline and return a ``RAGResponse``-shaped result.

    This is the entry point used by
    :meth:`LegalService._rag_answer` when ``RAG_USE_LANGGRAPH=true`` is
    set. Output is intentionally shape-compatible with
    :meth:`RAGEngine.answer` so the caller's handling is unchanged.
    ``evaluation_mode=True`` propagates the terse benchmark prompt
    selection through the graph's generate node.
    """
    compiled = get_compiled_graph()
    initial: RAGGraphState = {
        "query": query,
        "top_k": top_k,
        "evaluation_mode": evaluation_mode,
        "jurisdiction": jurisdiction,
    }
    # Threading the LangChain callbacks + run_name + tags into ainvoke is
    # what makes the whole graph land as a single nested trace tree in
    # LangSmith. The five node names (retrieve / rerank / generate /
    # validate / finalize) become child spans of "rag.graph"
    # automatically — no per-node decorator needed. When tracing is
    # disabled, get_callbacks() returns [] and this dict is a free
    # passthrough.
    config: dict[str, Any] = {
        "run_name": "rag.graph",
        "tags": [*lc_settings.default_tags, "rag", "langgraph"],
        "metadata": {
            "evaluation_mode": bool(evaluation_mode),
            "top_k": int(top_k),
            "jurisdiction": jurisdiction,
        },
        "callbacks": get_callbacks(),
    }
    final: dict[str, Any] = await compiled.ainvoke(initial, config=config)
    return GraphRAGResponse(
        answer=final.get("answer", ""),
        sources=final.get("cited_chunks", []) or [],
        confidence=float(final.get("confidence", 0.0) or 0.0),
    )
