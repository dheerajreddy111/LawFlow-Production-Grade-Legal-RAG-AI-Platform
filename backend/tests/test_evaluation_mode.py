"""Evaluation-mode regressions.

The eval flag is the central reason production answers can stay rich
without sandbagging benchmark F1. These tests pin the contract from
both sides:

  - PRODUCTION (evaluation_mode=False — the default) keeps the full
    markdown framing, citations, disclaimer, multi-section formatting.
  - EVAL MODE (evaluation_mode=True) returns a terse string: just the
    statutory content, no scaffolding.

If a future change reintroduces scaffolding under the eval flag — or
strips scaffolding from the chat surface — these tests fail and force
a deliberate decision.
"""

from __future__ import annotations

from app.evaluation.normalize import normalize_for_eval
from app.routing.engine import Route
from app.services.legal_service import _compose_answer
from app.services.statute_service import SectionResult


def _section(number: str = "302") -> SectionResult:
    return SectionResult(
        number=number,
        title="Punishment for murder",
        content=(
            "Whoever commits murder shall be punished with death, "
            "or imprisonment for life, and shall also be liable to fine."
        ),
        citations=["Bachan Singh v. State of Punjab, AIR 1980 SC 898"],
        act="Indian Penal Code, 1860",
        unit="section",
    )


# ── Production answer remains rich (regression guard) ───────────────────────


def test_compose_answer_production_keeps_scaffolding():
    """Default mode must still emit the full markdown answer the chat UI
    relies on — headings, primary-provision framing, key-authority line,
    disclaimer."""
    text = _compose_answer(Route.DETERMINISTIC, [_section()], "test reason")
    # Production framing markers
    assert "**Primary provision**" in text
    assert "**Section 302" in text
    assert "*Key authority:*" in text
    assert "This is legal information, not legal advice" in text
    # Statutory body is still there.
    assert "Whoever commits murder" in text


def test_compose_answer_rag_route_keeps_framing():
    """RAG route's 'Based on your question…' framing survives default mode."""
    text = _compose_answer(Route.RAG, [_section()], "test reason")
    assert "Based on your question" in text
    assert "This is legal information, not legal advice" in text


# ── Eval mode strips everything down to content ─────────────────────────────


def test_compose_answer_eval_mode_is_terse():
    """Eval mode returns just the section body — no scaffolding at all."""
    text = _compose_answer(
        Route.DETERMINISTIC, [_section()], "test reason", evaluation_mode=True
    )
    # Scaffolding gone
    assert "Primary provision" not in text
    assert "**Section 302" not in text
    assert "Key authority" not in text
    assert "legal information, not legal advice" not in text
    assert "Based on your question" not in text
    # Substantive content remains
    assert "Whoever commits murder" in text
    assert "imprisonment for life" in text
    # One short paragraph (single newline-free string, after the join).
    assert "\n\n" not in text


def test_compose_answer_eval_mode_no_sections_returns_marker():
    """A miss in eval mode emits the deterministic no-provision marker."""
    text = _compose_answer(
        Route.DETERMINISTIC, [], "no entities", evaluation_mode=True
    )
    assert text == "No relevant provision in the corpus."
    # No markdown, no disclaimer, no recovery hints.
    assert "**" not in text
    assert "legal information" not in text


def test_compose_answer_eval_mode_joins_multiple_sections():
    """Eval mode joins multiple section bodies with a single space."""
    text = _compose_answer(
        Route.RAG,
        [_section("302"), _section("304B")],
        "topic match",
        evaluation_mode=True,
    )
    # Both contents present, no separator scaffolding between them.
    assert text.count("Whoever commits murder") == 2
    assert "**" not in text
    assert "Section " not in text  # the corpus content doesn't repeat this header


# ── normalize_for_eval ─────────────────────────────────────────────────────


def test_normalize_lowercases_and_collapses_whitespace():
    assert (
        normalize_for_eval("Section   302\n\n  Punishment  for MURDER.")
        == "section 302 punishment for murder"
    )


def test_normalize_strips_pipeline_scaffolding():
    """Citation markers, source parens, dashes, disclaimers all gone."""
    text = (
        "**Section 302 — Punishment for murder**\n\n"
        "Whoever commits murder [1] (source: IPC) shall be punished. "
        "This is legal information, not legal advice."
    )
    out = normalize_for_eval(text)
    assert "[1]" not in out
    assert "source:" not in out
    assert "legal information" not in out
    assert "section 302" not in out  # the header line is stripped wholesale
    assert "whoever commits murder shall be punished" in out


def test_normalize_idempotent():
    once = normalize_for_eval("Section 302 — Punishment for murder. [1]")
    twice = normalize_for_eval(once)
    assert once == twice


def test_normalize_keeps_section_marker_and_percent():
    """`§` and `%` carry meaning in legal text — must not be stripped."""
    out = normalize_for_eval("§185 prescribes a 30% blood-alcohol limit.")
    assert "§185" in out
    assert "30%" in out


def test_normalize_empty_input():
    assert normalize_for_eval("") == ""
    assert normalize_for_eval("   \n\t  ") == ""


# ── RAGEngine evaluation_mode plumbing ─────────────────────────────────────


def test_rag_engine_build_prompt_eval_mode_omits_citation_cue():
    """The eval user template tells the model to skip [n] markers."""
    from app.rag.engine import RetrievedChunk, _build_prompt

    chunks = [
        RetrievedChunk(
            text="Whoever commits murder shall be punished with death.",
            source="IPC §302",
            score=0.9,
            metadata={},
        )
    ]
    prod_prompt = _build_prompt("punishment for murder?", chunks)
    eval_prompt = _build_prompt(
        "punishment for murder?", chunks, evaluation_mode=True
    )
    assert "citing them as [n]" in prod_prompt
    assert "citing them as [n]" not in eval_prompt
    assert "one short sentence" in eval_prompt.lower()
    assert "No citations" in eval_prompt or "no citations" in eval_prompt.lower()


def test_rag_engine_eval_system_prompt_is_terse_directive():
    from app.rag.engine import _EVAL_SYSTEM_PROMPT, _SYSTEM_PROMPT

    # Eval prompt is strict about format
    assert "ONE short sentence" in _EVAL_SYSTEM_PROMPT
    assert "[1]" in _EVAL_SYSTEM_PROMPT  # explicitly forbids these
    assert "disclaimer" in _EVAL_SYSTEM_PROMPT.lower()
    # Production prompt unchanged
    assert "LawFlow" in _SYSTEM_PROMPT
    assert "[1]" in _SYSTEM_PROMPT  # production REQUIRES them


# ── LangGraph state carries the flag ───────────────────────────────────────


def test_langgraph_state_includes_evaluation_mode():
    from app.graphs.rag_graph import RAGGraphState

    # `evaluation_mode` is an optional TypedDict field — present in
    # __annotations__ so the type checker enforces it on assignment.
    annotations = getattr(RAGGraphState, "__annotations__", {})
    assert "evaluation_mode" in annotations
