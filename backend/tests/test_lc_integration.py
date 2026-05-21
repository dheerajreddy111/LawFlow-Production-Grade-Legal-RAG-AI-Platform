"""Regression tests for the LangChain / LangSmith / LangGraph integration.

Invariants under test:

1. The response schema (shape + keys) is unchanged across the three
   routes (deterministic / rag / conversation).
2. The SSE event sequence is unchanged: ``meta → token+ → done`` (or
   a terminal ``error``).
3. Multi-turn memory follow-up resolution still works.
4. The opt-in LangGraph RAG path produces a response with the same
   shape as the native :class:`RAGEngine.answer` path.
5. The citation validator tool correctly flags hallucinated citations
   and reports cleanly when no citations are present.
6. LangChain wrappers (retriever, prompts, providers) import cleanly
   even when LangSmith is disabled.
"""

from __future__ import annotations

import json
import os

import pytest

from tests.conftest import needs_llm

# pytest-asyncio is in `auto` mode via pytest.ini — it picks up
# `async def` tests automatically. No module-wide pytestmark needed
# (would otherwise mark sync tests as asyncio and emit warnings).


# ── 1. Integration imports + scaffolding ─────────────────────────────────────

def test_lc_module_imports_clean():
    """The integration package must import cleanly regardless of env."""
    from app.integrations.lc import (  # noqa: F401
        configure_langsmith,
        get_callbacks,
        is_tracing_enabled,
        lc_settings,
        run_metadata,
        set_run_metadata,
        set_run_outputs,
        traced,
    )
    from app.integrations.lc.prompts import format_context, rag_prompt  # noqa: F401
    from app.integrations.lc.providers import (  # noqa: F401
        LangChainAnthropicProvider,
        LangChainGroqProvider,
        default_lc_provider,
    )
    from app.integrations.lc.retriever import build_retriever  # noqa: F401
    from app.integrations.lc.structured import (  # noqa: F401
        CitationReport,
        citation_validator_tool,
        validate_citations,
    )


def test_tracing_disabled_by_default():
    """With no LANGCHAIN_API_KEY in env, tracing must be off and callbacks empty."""
    from app.integrations.lc import get_callbacks, is_tracing_enabled

    # The conftest doesn't set tracing keys; the assertion is conditional
    # so that someone running with LangSmith locally isn't blocked.
    if not os.getenv("LANGCHAIN_API_KEY"):
        assert is_tracing_enabled() is False
        assert get_callbacks() == []


# ── 2. Citation validator (pure logic) ──────────────────────────────────────

def test_citation_validator_all_valid():
    from app.integrations.lc.structured import validate_citations

    r = validate_citations("See [1] and [2].", n_chunks=3)
    assert r.cited_indices == [1, 2]
    assert r.valid_indices == [1, 2]
    assert r.missing_indices == []
    assert r.all_valid is True
    assert r.any_citation is True


def test_citation_validator_flags_hallucinated_index():
    from app.integrations.lc.structured import validate_citations

    r = validate_citations("Per [1], murder is punishable. See also [7].", n_chunks=3)
    assert r.cited_indices == [1, 7]
    assert r.valid_indices == [1]
    assert r.missing_indices == [7]
    assert r.all_valid is False


def test_citation_validator_no_citations():
    from app.integrations.lc.structured import validate_citations

    r = validate_citations("This answer has no citation markers.", n_chunks=3)
    assert r.cited_indices == []
    assert r.valid_indices == []
    assert r.any_citation is False
    # "all_valid" is True when there are no citations to invalidate;
    # the graph's finalize node uses fallback semantics in that case.
    assert r.all_valid is True


def test_citation_validator_tool_returns_dict():
    """The LangChain @tool wrapper returns a JSON-serialisable dict."""
    from app.integrations.lc.structured import citation_validator_tool

    # @tool-wrapped functions are invoked via .invoke({...})
    out = citation_validator_tool.invoke({"answer": "[1] hello", "n_chunks": 1})
    assert isinstance(out, dict)
    assert out["cited_indices"] == [1]
    assert out["all_valid"] is True


# ── 3. LangChain retriever over the real VectorStore ────────────────────────

async def test_lc_retriever_returns_documents():
    """The BaseRetriever wrapper must return LangChain Documents from the
    existing VectorStore, with score in metadata."""
    from app.integrations.lc.retriever import build_retriever

    retriever = build_retriever(top_k=4, use_rerank=False)
    docs = await retriever.ainvoke("Section 420 IPC cheating")
    assert isinstance(docs, list)
    assert docs, "expected at least one hit from the bootstrapped corpus"
    d0 = docs[0]
    assert d0.page_content
    assert isinstance(d0.metadata, dict)
    assert "source" in d0.metadata
    assert "_score" in d0.metadata
    assert 0.0 <= float(d0.metadata["_score"]) <= 1.0


async def test_lc_retriever_rerank_path():
    """``use_rerank=True`` returns reranked Documents with rerank metadata."""
    from app.integrations.lc.retriever import build_retriever

    retriever = build_retriever(top_k=8, use_rerank=True)
    docs = await retriever.ainvoke("cheating and dishonestly inducing delivery")
    assert docs, "rerank should not erase all docs from a clear topical match"
    # Rerank metadata is added when rerank is applied.
    assert "_rerank_score" in (docs[0].metadata or {})


# ── 4. Response-shape regressions ────────────────────────────────────────────

EXPECTED_KEYS = {
    "query",
    "answer",
    "intent",
    "confidence",
    "entities",
    "route",
    "reason",
    "statute_sections",
    "domain",
    "related_acts",
    "suggestions",
}


async def test_response_shape_deterministic():
    """Deterministic route must return the full schema with route='deterministic'."""
    from app.services.legal_service import LegalService

    svc = LegalService()
    r = await svc.process_query("What does Section 302 IPC say?", session_id="r1")
    assert set(r.keys()) >= EXPECTED_KEYS
    assert r["route"] == "deterministic"
    assert isinstance(r["statute_sections"], list)
    assert isinstance(r["answer"], str) and r["answer"]
    assert isinstance(r["entities"], list)


async def test_response_shape_conversation():
    """Conversation route returns full schema with empty legal data."""
    from app.services.legal_service import LegalService

    svc = LegalService()
    r = await svc.process_query("hello!", session_id="r2")
    assert set(r.keys()) >= EXPECTED_KEYS
    assert r["route"] == "conversation"
    assert r["statute_sections"] == []
    assert r["domain"] is None
    assert r["related_acts"] == []
    assert r["suggestions"] == []


async def test_followup_memory_resolution():
    """Memory still resolves subjectless follow-ups against the last anchor."""
    from app.services.legal_service import LegalService

    svc = LegalService()
    # Anchor turn: deterministic Section 420 IPC.
    r1 = await svc.process_query(
        "What does Section 420 of the IPC say?", session_id="mem-test"
    )
    assert r1["route"] == "deterministic"
    # Follow-up — should be resolved against §420 via memory.
    r2 = await svc.process_query(
        "What is the punishment?", session_id="mem-test"
    )
    # We don't assert exact words, only that the memory layer triggered
    # — visible as a "follow-up" note appended to the reason string by
    # `ConversationMemory.resolve`.
    assert "follow-up" in r2["reason"].lower() or "regarding" in r2["reason"].lower(), \
        f"expected follow-up resolution to be visible in reason; got: {r2['reason']!r}"


# ── 5. SSE streaming sequence ───────────────────────────────────────────────

async def test_sse_event_sequence_deterministic():
    """SSE stream emits meta → token+ → done; no error frame on the happy path."""
    from app.services.legal_service import LegalService
    from app.services.streaming import query_event_stream

    svc = LegalService()

    async def process(q: str) -> dict:
        return await svc.process_query(q, session_id="sse1")

    events: list[tuple[str, dict]] = []
    async for frame in query_event_stream("What does Section 302 IPC say?", process):
        assert frame.startswith("event: ")
        # Parse one SSE frame: "event: X\ndata: {...}\n\n"
        lines = frame.strip().split("\n", 1)
        event_name = lines[0][len("event: "):]
        data_line = lines[1][len("data: "):]
        events.append((event_name, json.loads(data_line)))

    names = [name for name, _ in events]
    # First event must be meta; last must be done; everything between is token.
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert all(n == "token" for n in names[1:-1])
    # meta must carry the same key set the frontend depends on
    meta_data = events[0][1]
    expected_meta_keys = {
        "query", "intent", "route", "confidence", "reason", "entities",
        "statute_sections", "domain", "related_acts", "suggestions",
    }
    assert set(meta_data.keys()) >= expected_meta_keys
    assert meta_data["route"] == "deterministic"


# ── 6. LangGraph parity (opt-in path, behind flag) ──────────────────────────

@needs_llm
async def test_langgraph_rag_path_matches_response_shape(monkeypatch):
    """With RAG_USE_LANGGRAPH=true, RAG queries flow through the graph but
    the response schema is identical."""
    # Force a fresh LCSettings read with the flag on.
    monkeypatch.setenv("RAG_USE_LANGGRAPH", "true")
    import importlib

    import app.integrations.lc.settings as lc_settings_mod

    importlib.reload(lc_settings_mod)
    # Re-export the freshly-read snapshot under the package namespace.
    import app.integrations.lc as lc_pkg
    lc_pkg.lc_settings = lc_settings_mod.lc_settings  # type: ignore[attr-defined]

    from app.services.legal_service import LegalService

    svc = LegalService()
    r = await svc.process_query(
        "Can the police arrest someone without a warrant?",
        session_id="graph-test",
    )
    assert set(r.keys()) >= EXPECTED_KEYS
    assert r["route"] == "rag"
    assert r["answer"]
    assert isinstance(r["statute_sections"], list)


# ── 7. Citation validator inside the graph’s finalize step ──────────────────

async def test_graph_finalize_drops_hallucinated_citations():
    """Direct unit test of the graph's finalize semantics — no LLM call."""
    from langchain_core.documents import Document

    from app.graphs.rag_graph import _finalize_node

    docs = [
        Document(
            page_content="text-A",
            metadata={"source": "src-A", "_score": 0.8},
        ),
        Document(
            page_content="text-B",
            metadata={"source": "src-B", "_score": 0.6},
        ),
    ]
    state = {
        "query": "q",
        "reranked": docs,
        "answer": "Per [1] and [7].",
        "citation_report": {
            "cited_indices": [1, 7],
            "valid_indices": [1],
            "missing_indices": [7],
            "n_chunks": 2,
            "all_valid": False,
            "any_citation": True,
        },
    }
    out = _finalize_node(state)
    assert len(out["cited_chunks"]) == 1
    assert out["cited_chunks"][0].source == "src-A"
    # Confidence is mean similarity of the kept chunks.
    assert abs(out["confidence"] - 0.8) < 1e-6
