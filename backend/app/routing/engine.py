"""
Routing decision engine for LawFlow.

Given a classified intent and extracted entities, determines how a query
should be handled downstream:

    deterministic  – one or more high-confidence statutory / citation entities
                     exist; the answer can be looked up directly from the corpus
                     without generation.
    rag            – open-ended research or document-summary intent, OR any
                     query without a specific provision; requires
                     retrieval-augmented generation.
    unknown        – retained in the enum for compatibility, but no longer
                     produced: a legal assistant should attempt research
                     rather than dead-end conversational legal questions.

Rules (evaluated in priority order):
    1. Any ACT / SECTION / ARTICLE / LEGAL_CITATION entity with
       confidence ≥ 0.80  →  deterministic
    2. Intent is legal_research or document_summary  →  rag
    3. Everything else  →  rag  (conversational legal-question default)

Example outputs:
    decide("bare_act_query",  [ACT:"IPC" 0.93, SECTION:"Section 420" 0.93])
        → {"route": "deterministic", "reason": "SECTION entity 'Section 420' detected (confidence 0.93)"}

    decide("legal_research",  [])
        → {"route": "rag", "reason": "intent is legal_research"}

    decide("case_lookup",     [COURT:"Delhi High Court" 0.95])
        → {"route": "rag", "reason": "no specific provision identified — defaulting to legal research"}
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from app.entities.extractor import EntityType, LegalEntity
from app.intents.classifier import Intent

# ── Public types ──────────────────────────────────────────────────────────────

class Route(str, Enum):
    DETERMINISTIC = "deterministic"
    RAG           = "rag"
    CONVERSATION  = "conversation"
    UNKNOWN       = "unknown"


class RoutingDecision(BaseModel):
    route:  str
    reason: str


# ── Constants ─────────────────────────────────────────────────────────────────

# Entity types that warrant deterministic routing when confidence is sufficient.
# COURT is excluded: knowing the forum doesn't tell us *what* to retrieve.
_DETERMINISTIC_TYPES: frozenset[str] = frozenset({
    EntityType.ACT,
    EntityType.SECTION,
    EntityType.ARTICLE,
    EntityType.LEGAL_CITATION,
})

# Minimum entity confidence required to trigger deterministic routing.
# Set at 0.80 to exclude low-signal matches (bare "AIR 1978" at 0.72,
# unnamed acts without a year at 0.78) while accepting all specific patterns.
_ENTITY_CONFIDENCE_THRESHOLD: float = 0.80

# Intents that require RAG generation.
# LEGAL_OVERVIEW joins LEGAL_RESEARCH / DOCUMENT_SUMMARY here because
# broad "tell me about the MV Act" queries need retrieval-grounded
# answers, just with a different prompt + diversification strategy
# downstream. The legal_service inspects the intent on the way out and
# switches into overview-mode retrieval when it sees LEGAL_OVERVIEW.
_RAG_INTENTS: frozenset[str] = frozenset({
    Intent.LEGAL_RESEARCH,
    Intent.DOCUMENT_SUMMARY,
    Intent.LEGAL_OVERVIEW,
})


# ── Engine ────────────────────────────────────────────────────────────────────

class DecisionEngine:
    """Stateless routing engine — safe to share across async tasks."""

    async def decide(
        self,
        intent: str,
        entities: list[LegalEntity],
    ) -> RoutingDecision:
        # Rule 0 — conversation. Greetings/pleasantries get a conversational
        # reply only; never any retrieval or generation.
        if intent == Intent.CONVERSATION:
            return RoutingDecision(
                route=Route.CONVERSATION,
                reason="conversational input — no legal retrieval",
            )

        # Rule 1 — deterministic entity check.
        # LEGAL_OVERVIEW deliberately bypasses this: the user named an
        # Act ("explain the IT Act") but they want a summary, not a
        # section lookup. Sending overview queries through the
        # deterministic statute service would surface a single
        # arbitrary section instead of the act-wide overview.
        if intent != Intent.LEGAL_OVERVIEW:
            anchor = _best_deterministic_entity(entities)
            if anchor is not None:
                return RoutingDecision(
                    route=Route.DETERMINISTIC,
                    reason=(
                        f"{anchor.type} entity '{anchor.value}' detected"
                        f" (confidence {anchor.confidence})"
                    ),
                )

        # Rule 2 — RAG intents (legal_research / document_summary). The
        # classifier's broad legal-vocabulary floor maps any legal-ish
        # question here, so genuine legal queries still reach RAG.
        if intent in _RAG_INTENTS:
            return RoutingDecision(
                route=Route.RAG,
                reason=f"intent is {intent}",
            )

        # Rule 3 — fallback. Not a greeting, no provision, not legal-ish:
        # a non-legal / unclassifiable query. Ask for clarification rather
        # than firing RAG and surfacing irrelevant provisions.
        return RoutingDecision(
            route=Route.UNKNOWN,
            reason="no legal intent or provision identified",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _best_deterministic_entity(entities: list[LegalEntity]) -> LegalEntity | None:
    """Return the highest-confidence deterministic entity, or None."""
    candidates = [
        e for e in entities
        if e.type in _DETERMINISTIC_TYPES
        and e.confidence >= _ENTITY_CONFIDENCE_THRESHOLD
    ]
    return max(candidates, key=lambda e: e.confidence) if candidates else None
