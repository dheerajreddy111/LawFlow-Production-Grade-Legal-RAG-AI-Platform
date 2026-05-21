"""Broad-topic legal-overview routing regressions.

Pins three properties that distinguish the new ``LEGAL_OVERVIEW`` path
from the existing intents:

  - Broad informational phrases ("tell me about X", "explain the X
    Act", "what does X cover", "overview of X") classify as
    ``legal_overview`` — not as ``unknown`` (which dead-ends in the
    clarification flow) and not as ``bare_act_query`` (which routes to
    a section lookup).
  - The routing engine sends ``legal_overview`` to RAG even when the
    entity extractor detected an Act — the user wants a summary, not a
    deterministic section pull.
  - Section-specific lookups still beat the overview pattern when both
    could match (e.g. "Tell me about Section 302 IPC" stays
    deterministic).

If a future change re-routes overview queries to deterministic, or
sends section queries through overview, this file fails.
"""

from __future__ import annotations

import asyncio

import pytest

from app.entities.extractor import EntityExtractor
from app.intents.classifier import IntentClassifier
from app.routing.engine import DecisionEngine, Route


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Intent classification ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "Tell me about the Motor Vehicles Act",
        "Explain the IT Act",
        "What is the Constitution of India?",
        "What does the Consumer Protection Act cover?",
        "Overview of the Companies Act",
        "Give me an overview of the Companies Act",
        "Introduction to the Arbitration Act",
        "What is the purpose of the RTI Act?",
        "Main provisions of the Patents Act",
    ],
)
def test_broad_legal_phrases_classify_as_overview(query: str) -> None:
    """The broad-overview cues must beat fallback to unknown / research."""
    c = IntentClassifier()
    res = _run(c.classify(query))
    assert res.intent == "legal_overview", (
        f"{query!r} → {res.intent} (expected legal_overview)"
    )


def test_section_specific_query_stays_bare_act() -> None:
    """`Tell me about Section 302 IPC` must NOT be overview — section
    citations beat the overview cue via priority + weight."""
    c = IntentClassifier()
    res = _run(c.classify("Tell me about Section 302 IPC"))
    assert res.intent == "bare_act_query"


def test_open_research_still_routes_research() -> None:
    """Open scenario questions remain legal_research — not overview."""
    c = IntentClassifier()
    res = _run(c.classify("Can I drink and drive in India?"))
    assert res.intent == "legal_research"


def test_greeting_still_routes_conversation() -> None:
    c = IntentClassifier()
    res = _run(c.classify("Hi LawFlow"))
    assert res.intent == "conversation"


# ── Routing decisions ──────────────────────────────────────────────────────


def test_overview_routes_to_rag_even_when_act_entity_detected() -> None:
    """The routing engine must suppress the deterministic anchor when
    the intent is legal_overview — the user wants a summary."""
    e = EntityExtractor()
    r = DecisionEngine()
    extraction = _run(e.extract("Explain the IT Act"))
    decision = _run(
        r.decide(intent="legal_overview", entities=extraction.entities)
    )
    assert decision.route == Route.RAG


def test_section_query_still_deterministic() -> None:
    """Section citations + bare_act_query intent stay deterministic."""
    e = EntityExtractor()
    r = DecisionEngine()
    extraction = _run(e.extract("What is Section 302 of IPC?"))
    decision = _run(
        r.decide(intent="bare_act_query", entities=extraction.entities)
    )
    assert decision.route == Route.DETERMINISTIC


def test_unknown_still_unknown() -> None:
    """Genuine non-legal noise still reaches the clarification flow."""
    r = DecisionEngine()
    decision = _run(r.decide(intent="unknown", entities=[]))
    assert decision.route == Route.UNKNOWN


# ── _compose_overview_answer ───────────────────────────────────────────────


def test_compose_overview_lists_provisions_grounded_in_sample() -> None:
    """The LLM-less overview composer must lift its bullets verbatim
    from the retrieved section sample — no hallucination."""
    from app.services.legal_service import _compose_overview_answer
    from app.services.statute_service import SectionResult

    sections = [
        SectionResult(
            number="3",
            title="Necessity for driving licence",
            content="No person shall drive a motor vehicle in any public place...",
            citations=[],
            act="Motor Vehicles Act, 1988",
            unit="section",
        ),
        SectionResult(
            number="39",
            title="Necessity for registration",
            content="No person shall drive any motor vehicle unless registered...",
            citations=[],
            act="Motor Vehicles Act, 1988",
            unit="section",
        ),
        SectionResult(
            number="185",
            title="Driving by a drunken person or under influence of drugs",
            content="Whoever has alcohol exceeding 30 mg per 100 ml...",
            citations=[],
            act="Motor Vehicles Act, 1988",
            unit="section",
        ),
    ]
    out = _compose_overview_answer(sections)
    # Headline + bulleted section titles.
    assert "Motor Vehicles Act, 1988" in out
    assert "Major areas covered" in out
    assert "Section 3" in out and "Necessity for driving licence" in out
    assert "Section 39" in out and "Necessity for registration" in out
    assert "Section 185" in out and "drunken" in out
    # Grounded ending — disclaimer is present.
    assert "legal information" in out
    # No invented sections (e.g. "Section 100" isn't in the sample).
    assert "Section 100" not in out


def test_compose_overview_handles_multiple_acts() -> None:
    """When the sample spans multiple acts, the dominant act is named
    first and the others appear under 'Related provisions'."""
    from app.services.legal_service import _compose_overview_answer
    from app.services.statute_service import SectionResult

    sections = [
        SectionResult(number="302", title="Murder", content="...",
                       citations=[], act="Indian Penal Code, 1860", unit="section"),
        SectionResult(number="420", title="Cheating", content="...",
                       citations=[], act="Indian Penal Code, 1860", unit="section"),
        SectionResult(number="101", title="Murder", content="...",
                       citations=[], act="Bharatiya Nyaya Sanhita, 2023", unit="section"),
    ]
    out = _compose_overview_answer(sections)
    # IPC wins by count and is named as primary.
    assert "Indian Penal Code, 1860" in out
    assert "Related provisions" in out
    assert "Bharatiya Nyaya Sanhita, 2023" in out


def test_compose_overview_empty_returns_empty() -> None:
    """An empty section list returns an empty string — never invents."""
    from app.services.legal_service import _compose_overview_answer

    assert _compose_overview_answer([]) == ""


# ── _compose_answer no-provision overview fallback ─────────────────────────


def test_overview_llm_unavailable_still_returns_grounded_overview() -> None:
    """When the LLM raises (rate limit, missing key, network error)
    AND the user asked for an overview of an indexed Act, the fallback
    must compose a deterministic "Major areas covered" answer from
    the act-wide chunk sample — NOT incorrectly claim the act isn't
    indexed.

    This regression specifically guards against the case where the
    chat UI showed "I don't have this Act indexed in the LawFlow
    corpus yet." for "Tell me about the MV Act" while MV Act WAS in
    the index.
    """
    import asyncio
    from unittest.mock import AsyncMock

    from app.rag.engine import LLMNotConfiguredError, RAGEngine
    from app.rag.ingest import ingest_corpora
    from app.services.legal_service import LegalService

    async def run() -> None:
        await ingest_corpora()
        svc = LegalService()
        # Force the RAG path to fail the LLM call — every realistic
        # failure mode (rate limit / missing key / 5xx) is caught
        # behind the same boundary in _rag_answer.
        svc.rag = RAGEngine()
        svc.rag.generate = AsyncMock(  # type: ignore[assignment]
            side_effect=LLMNotConfiguredError("simulated LLM unavailability")
        )

        result = await svc.process_query(
            "Tell me about the Motor Vehicles Act"
        )

        # The honest grounded-overview path fired.
        assert result["intent"] == "legal_overview"
        assert "Motor Vehicles Act" in result["answer"]
        assert "Major areas covered" in result["answer"]
        # At least a few section titles from the act show up.
        body = result["answer"]
        section_hits = sum(
            1
            for label in (
                "driving licence",
                "registration",
                "drunken person",
                "insurance",
                "compensation",
            )
            if label.lower() in body.lower()
        )
        assert section_hits >= 2, (
            "Expected at least 2 indexed-section titles in the overview"
        )
        # Critical regression guard — the bug message MUST NOT appear.
        assert "don't have this Act indexed" not in body
        assert "not currently indexed" not in body
        # The chunks came from retrieval and the row carries them so
        # the explainability panel works.
        assert len(result["retrieved_chunks"]) >= 5

    asyncio.new_event_loop().run_until_complete(run())


def test_overview_llm_unavailable_unrecognised_act_says_so() -> None:
    """LLM-unavailable + Act not in registry → "couldn't identify which
    Act". Distinct from the "indexed but no chunks" diagnostic."""
    import asyncio
    from unittest.mock import AsyncMock

    from app.rag.engine import LLMNotConfiguredError, RAGEngine
    from app.rag.ingest import ingest_corpora
    from app.services.legal_service import LegalService

    async def run() -> None:
        await ingest_corpora()
        svc = LegalService()
        svc.rag = RAGEngine()
        svc.rag.generate = AsyncMock(  # type: ignore[assignment]
            side_effect=LLMNotConfiguredError("simulated")
        )
        result = await svc.process_query("Tell me about the Foobar Act")
        body = result["answer"]
        # Unrecognised → "couldn't identify which Act"
        assert "couldn't identify which Act" in body
        # Not the "transient retrieval issue" or "not indexed" branch.
        assert "Retrieval returned no passages" not in body
        assert "don't have this Act indexed" not in body
        # Lists available acts so the user can re-ask.
        assert "Available legal sources right now" in body

    asyncio.new_event_loop().run_until_complete(run())


def test_compose_answer_overview_no_provision_honest_response() -> None:
    """Overview asked for an Act we don't carry → honest 'not indexed'.

    The list of "what we DO carry" is now runtime-derived from
    ``ACT_REGISTRY`` via ``corpus_status.supported_acts_brief``, so it
    uses canonical short titles ('IPC', 'MV Act') rather than the
    formal long names.
    """
    from app.routing.engine import Route as R
    from app.services.legal_service import _compose_answer

    out = _compose_answer(
        R.RAG, [], "no act resolved", overview_mode=True
    )
    assert "don't have this Act indexed" in out
    # The fallback lists what IS available — short canonical titles.
    assert "IPC" in out and "MV Act" in out
