"""
LegalService — orchestrates the query-processing pipeline.

Flow:
    1. IntentClassifier + EntityExtractor  (parallel)
    2. DecisionEngine                      → deterministic | rag
    3. Retrieval / generation:
         deterministic → StatuteService entity lookup (no LLM)
         rag           → RAGEngine.answer() (semantic retrieval + Groq),
                         with deterministic statute composition as a
                         graceful fallback if generation is unavailable.

The response schema, citations, confidence scoring and streaming contract
are unchanged: `answer` is always a grounded markdown string and
`statute_sections` always carries renderable provisions + citations.
"""

import asyncio
import json
import logging
from typing import Any

from app.entities.extractor import EntityExtractor
from app.integrations.lc import set_run_metadata, set_run_outputs, traced
from app.intents.classifier import IntentClassifier
from app.rag.engine import RAGEngine, RetrievedChunk
from app.routing.engine import DecisionEngine, Route
from app.services.act_registry import (
    act_key_for_name,
    legal_context,
    resolve_act,
)
from app.services.memory import Turn, build_subject, conversation_memory
from app.services.metrics import metrics
from app.services.statute_service import SectionResult, StatuteService

logger = logging.getLogger(__name__)

# Conversational scaffolding (greeting, thanks, clarify). The capability
# claims inside `_greeting()` and `_clarify()` are derived from the
# live :mod:`app.services.corpus_status` snapshot so the prose can't
# drift from what's actually indexed. Constants below are *templates*
# the helpers fill in.

_THANKS = (
    "You're welcome! Feel free to ask another Indian law question — a "
    "specific section, or a practical legal scenario — whenever you're "
    "ready."
)


def _format_act_list(acts: list[str], max_items: int = 8) -> str:
    """Render an act list as readable prose with an "and N more" tail.

    Used by the greeting / clarification helpers so they don't dump a
    20-item list onto the user. The cap keeps the message readable
    while staying honest — "and N more" links back to the System
    Health page's full list.
    """
    if not acts:
        return ""
    if len(acts) <= max_items:
        return ", ".join(acts)
    head = ", ".join(acts[:max_items])
    return f"{head}, and {len(acts) - max_items} more"


def _greeting() -> str:
    """Build the greeting from the live registry rather than a constant.

    Reads only the registry (sync; see ``corpus_status.supported_acts_brief``);
    this fires inside the request critical path and we don't want to
    serialise on a Chroma round-trip. The registry is the deployment
    contract: every act listed here is supposed to be ingested by the
    lifespan, and the System Health page surfaces any drift.
    """
    from app.services.corpus_status import supported_acts_brief

    supported = supported_acts_brief()
    bullet = _format_act_list(supported, max_items=10)
    return (
        "Hello! I'm **LawFlow**, your Indian legal AI assistant.\n\n"
        "I can help you with:\n\n"
        f"- Statutory provisions from the {len(supported)} acts in the "
        f"corpus, including {bullet}\n"
        "- Plain-language answers to practical legal questions, grounded "
        "in the relevant law\n"
        "- Looking up a specific section / article, or asking for an "
        "overview of an Act (e.g. *“Tell me about the Motor Vehicles "
        "Act”*)\n\n"
        "Ask me something like *“What does Section 302 of the IPC say?”* "
        "or *“Can the police arrest someone without a warrant?”* to get "
        "started."
    )


def _clarify() -> str:
    """Clarification fallback when routing can't infer an intent.

    Domain examples are deliberately short — the goal is to nudge the
    user toward a question shape, not catalogue every supported act.
    The greeting + System Health surface the full capability list."""
    return (
        "I want to help — could you share a bit more detail about the "
        "legal issue?\n\n"
        "I'm strongest on Indian law: statutes and provisions, criminal "
        "and constitutional matters, procedure, evidence, consumer, "
        "contract, motor-vehicle, cyber, IP, and family-law questions. "
        "It helps if you mention **what happened** or **the area of "
        "law**.\n\n"
        "For example, you could ask:\n\n"
        "- *“What is the punishment for cheating?”*\n"
        "- *“Can the police arrest someone without a warrant?”*\n"
        "- *“What does Section 302 of the IPC say?”*\n"
        "- *“Tell me about the Motor Vehicles Act”*\n\n"
        "Rephrase your question with one of those in mind and I'll take "
        "it from there."
    )


def _conversational_answer(query: str, route: "Route") -> str:
    """Canned reply for conversation/unknown routes — no retrieval, no LLM.

    The greeting + clarify text is composed from the live registry on
    every call so capability claims stay accurate when a new act is
    added or removed. The constants used to bake the act list at
    import time; that drifted whenever ``ACT_REGISTRY`` changed.
    """
    if route == Route.UNKNOWN:
        return _clarify()
    q = query.strip().lower()
    if q.startswith(("thank", "thanx", "thx", "ty", "cheers", "appreciate")):
        return _THANKS
    return _greeting()


def _compose_answer(
    route: Route,
    sections: list[SectionResult],
    reason: str,
    *,
    evaluation_mode: bool = False,
    overview_mode: bool = False,
) -> str:
    """Build a grounded answer from retrieved provisions.

    The same retrieval-grounded summary serves both routes: deterministic
    (exact entity hits) and RAG (topic/keyword cross-act hits). No LLM is
    used — the explanation is composed deterministically from the corpus.

    Production callers (chat UI, API) get the full markdown answer with
    primary-provision framing, key authority citations, and the
    "legal information, not legal advice" disclaimer.

    ``evaluation_mode=True`` returns a terse, scaffolding-free string —
    just the joined section content — so benchmark scoring measures
    *content* rather than the wrapper. Only the evaluation harness ever
    flips this; production answers are unaffected.

    ``overview_mode=True`` returns a "Primary legal source / The Act
    covers …" summary instead of full statutory text — used as the
    LLM-less fallback for broad informational queries. The bullet
    list is composed from the section titles in the retrieved
    sample, so the output is still strictly corpus-grounded.
    """
    if sections:
        if evaluation_mode:
            # Benchmark variant — emit just the substantive statutory
            # content, joined by a single space when multiple provisions
            # are returned. No framing, no act labels, no disclaimer.
            # The evaluator's token-overlap metric reads this against
            # the expected_answer column directly.
            return " ".join(s.content.strip() for s in sections).strip()

        if overview_mode:
            # Overview fallback (no LLM available). Group by act,
            # surface "Major areas covered" as a bulleted list of
            # provision titles — strictly composed from the retrieved
            # sample so no fact is invented.
            return _compose_overview_answer(sections)

        # RAG-routed queries are conversational ("can police arrest…"),
        # resolved by topical retrieval — frame them as the most relevant
        # provisions rather than an exact-match lookup.
        if route == Route.RAG:
            intro = (
                "Based on your question, here is what the relevant Indian "
                "law provides. The most applicable provisions in the "
                "LawFlow corpus are:"
            )
        else:
            # Deterministic route returns the single exact match —
            # frame it as the primary provision, not a broad list.
            label = (
                "Primary provision" if len(sections) == 1 else "Primary provisions"
            )
            intro = f"**{label}** matching your query:"
        parts = [intro]
        for s in sections:
            unit = "Article" if s.unit == "article" else "Section"
            label = f"{unit} {s.number} — {s.title}"
            if s.act:
                label += f" ({s.act})"
            parts.append(f"**{label}**")
            parts.append(s.content.strip())
            if s.citations:
                lead = "; ".join(s.citations[:2])
                parts.append(f"*Key authority:* {lead}")
        parts.append(
            "This is legal information, not legal advice. Refer to the "
            "cited sources below for the authoritative text and judgments."
        )
        return "\n\n".join(parts)

    # No provision retrieved.
    if evaluation_mode:
        # A terse, deterministic miss-marker — the scorer can detect it
        # cheaply and the model never had to invent verbose framing.
        return "No relevant provision in the corpus."
    if overview_mode:
        # Overview asked for an Act we don't carry — give the user an
        # honest "we don't have this" with a runtime-accurate list of
        # the acts we DO carry. The list is read from
        # :mod:`app.services.corpus_status` so we never claim coverage
        # we don't have (and never *omit* coverage we just added).
        from app.services.corpus_status import supported_acts_brief

        listed = _format_act_list(supported_acts_brief(), max_items=30)
        return (
            "**I don't have this Act indexed in the LawFlow corpus yet.**\n\n"
            f"Available legal sources right now: {listed}. Ask for an "
            "overview of any of these, or cite a specific section / "
            "article for a precise lookup."
        )
    # Concise, professional guidance — deliberately silent about any
    # generation/LLM capability.
    if route == Route.DETERMINISTIC:
        return (
            "**I couldn't find that exact provision in the LawFlow corpus.**\n\n"
            "Try rephrasing with the Act name alongside the number "
            "(e.g. “Section 420 of the IPC” or “Section 138 NI Act”), or "
            "ask the underlying question in plain words and I'll point you "
            "to the relevant law."
        )
    return (
        "**I couldn't find a provision in the LawFlow corpus that directly "
        "addresses this.**\n\n"
        "Try naming the relevant Act or area of law — for example "
        "“Motor Vehicles Act”, “Section 138 NI Act”, or “Article 21” — "
        "and I'll return the exact statutory text and the leading judgments."
    )


def _compose_overview_answer(sections: list[SectionResult]) -> str:
    """LLM-less overview composer — used as the fallback path.

    Groups the retrieved sample by act, opens with a "primary legal
    source" line naming the dominant act, and emits a bulleted list
    of "Section X — Title" entries lifted from the sample. Every line
    is a verbatim provision title from the corpus, so there's nothing
    to hallucinate.

    When the sample spans multiple acts (e.g. a topic that touches
    both IPC and BNS) the dominant act by count is named first; the
    other acts get a "Related provisions:" tail.
    """
    if not sections:
        return ""

    # Bucket by act display name. Preserve first-seen order so the
    # output is deterministic.
    bucket: dict[str, list[SectionResult]] = {}
    for s in sections:
        act = (s.act or "Indian legal corpus").strip()
        bucket.setdefault(act, []).append(s)

    primary_act, primary_sections = max(
        bucket.items(), key=lambda kv: len(kv[1])
    )

    def _format_section(s: SectionResult) -> str:
        unit = "Article" if s.unit == "article" else "Section"
        title = (s.title or "Provision").strip()
        return f"- **{unit} {s.number}** — {title}"

    parts: list[str] = [
        "**Primary legal source matching your query:**",
        f"### {primary_act}",
        "Major areas covered (grounded in the retrieved provisions):",
        *[_format_section(s) for s in primary_sections],
    ]

    others = [a for a in bucket if a != primary_act]
    if others:
        parts.append("")
        parts.append("**Related provisions in other Acts:**")
        for act in others:
            parts.append(f"- {act}: " + ", ".join(
                f"{('Article' if s.unit == 'article' else 'Section')} {s.number}"
                for s in bucket[act]
            ))

    parts.append(
        "This is legal information, not legal advice. Ask about any "
        "listed provision for the full statutory text."
    )
    return "\n\n".join(parts)


# Excerpt length for the per-chunk explainability record. We surface a
# short window only — the panel is for *signals* (which chunk ranked where
# and why), not the full passage text. The cited sources card already
# renders the full provision text.
_CHUNK_EXCERPT_CHARS = 320


def _chunk_to_record(chunk: RetrievedChunk) -> dict:
    """Compact, serialisable view of one retrieved chunk for the API.

    Surfaces every retrieval stage the chunk passed through:

    - vector cosine similarity + rank inside the vector search
    - BM25 raw score + rank inside the lexical search
    - fused RRF score + rank
    - deterministic legal-signal rerank score (and its terse reason)
    - cross-encoder relevance score (when the encoder is enabled)

    Enough for an operator to debug *why* a chunk landed where it did
    in the final context window. The explainability panel renders the
    stages as horizontal bars side-by-side.
    """
    text = (chunk.text or "").strip()
    excerpt = text if len(text) <= _CHUNK_EXCERPT_CHARS else (
        text[: _CHUNK_EXCERPT_CHARS - 1] + "…"
    )
    meta = chunk.metadata or {}

    def _opt_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value), 4)
        except (TypeError, ValueError):
            return None

    def _opt_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return {
        "source": chunk.source,
        "similarity": round(float(chunk.score), 4),
        "rerank_score": (
            round(float(chunk.rerank_score), 4)
            if chunk.rerank_score is not None
            else None
        ),
        "rerank_reason": chunk.rerank_reason,
        "section": str(meta.get("extra.number") or meta.get("section_title") or ""),
        "act": str(meta.get("extra.act") or ""),
        "excerpt": excerpt,
        # Stage scores from app.rag.retrieval. All optional — older
        # ingestion paths and the LangGraph route may surface only a
        # subset.
        "vector_score": _opt_float(meta.get("_lf_vector_score")),
        "vector_rank": _opt_int(meta.get("_lf_vector_rank")),
        "bm25_score": _opt_float(meta.get("_lf_bm25_score")),
        "bm25_rank": _opt_int(meta.get("_lf_bm25_rank")),
        "fused_score": _opt_float(meta.get("_lf_fused_score")),
        "fused_rank": _opt_int(meta.get("_lf_fused_rank")),
        "cross_encoder_score": _opt_float(meta.get("_lf_cross_encoder_score")),
    }


def _subject_from_sections(sections: list[SectionResult]) -> str:
    """Authoritative conversational anchor from the *resolved* primary
    provision (e.g. 'Section 420 of the Indian Penal Code, 1860').

    This is unambiguous and re-parseable by the entity extractor, so a
    follow-up like 'what is the punishment?' resolves to the exact act —
    not whichever corpus happens to be first in registry order.
    """
    if not sections:
        return ""
    s = sections[0]
    unit = "Article" if getattr(s, "unit", "section") == "article" else "Section"
    return f"{unit} {s.number} of the {s.act}" if s.act else f"{unit} {s.number}"


class LegalService:
    def __init__(self) -> None:
        self.extractor  = EntityExtractor()
        self.classifier = IntentClassifier()
        self.router     = DecisionEngine()
        self.statutes   = StatuteService()
        self.rag        = RAGEngine()

    @staticmethod
    def _chunk_to_section(chunk: RetrievedChunk) -> SectionResult:
        """Reconstruct a SectionResult from a retrieved chunk so RAG sources
        render through the existing citation schema unchanged."""
        m = chunk.metadata or {}
        cites = m.get("extra.citations")
        if isinstance(cites, str):
            try:
                cites = json.loads(cites)
            except (ValueError, TypeError):
                cites = [cites] if cites else []
        if not isinstance(cites, list):
            cites = []
        return SectionResult(
            number=str(m.get("extra.number", "") or ""),
            title=str(
                m.get("extra.title")
                or m.get("section_title")
                or chunk.source
                or "Provision"
            ),
            content=chunk.text,
            citations=[str(c) for c in cites],
            act=(m.get("extra.act") or None),
            unit=str(m.get("extra.unit", "section") or "section"),
        )

    @traced(name="legal_service._rag_answer", run_type="chain")
    async def _rag_answer(
        self,
        query: str,
        entities: list,
        reason: str,
        *,
        evaluation_mode: bool = False,
        overview_mode: bool = False,
    ) -> tuple[str, list[SectionResult], list[dict]]:
        """RAG-routed answer: semantic retrieval + Groq generation, with a
        graceful fallback to deterministic statute composition.

        ``overview_mode=True`` activates the diversified act-wide
        retrieval substrate + the "summarise the Act" generation
        prompt. The flag is a hint, not a guarantee — if the rewriter
        can't resolve an act key the orchestrator falls through to
        normal hybrid retrieval. The fallback path (no LLM available)
        also honours overview_mode via ``_compose_answer``'s overview
        branch.
        """
        try:
            resp = await self._rag_invoke(
                query,
                evaluation_mode=evaluation_mode,
                overview_mode=overview_mode,
            )
            if resp.answer and resp.sources:
                sections = [
                    self._chunk_to_section(c) for c in resp.sources
                ]
                chunks = [_chunk_to_record(c) for c in resp.sources]
                return resp.answer, sections, chunks
            logger.info(
                "RAG produced no grounded sources — deterministic fallback"
            )
        except Exception as exc:  # noqa: BLE001 — boundary: degrade gracefully
            logger.warning(
                "RAG generation unavailable (%s: %s) — deterministic fallback",
                type(exc).__name__,
                exc,
            )
        # LLM-less fallback. Two paths, branched by ``overview_mode``:
        #
        # - Overview: re-run the act-wide retrieval directly and compose
        #   a deterministic "Major areas covered" summary from the
        #   chunks. We do NOT defer to ``self.statutes.retrieve(entities)``
        #   here because overview queries rarely carry section entities
        #   ("Tell me about MV Act" → no SECTION token), so the
        #   entity-based path returns nothing and the user wrongly
        #   sees "not indexed". Going through ``hybrid_retrieve`` in
        #   overview mode pulls the same diversified sample the LLM
        #   path used — so the *content* of the answer is identical
        #   between LLM-up and LLM-down, just rendered differently.
        # - Non-overview: original entity-based deterministic
        #   composition.
        if overview_mode:
            return await self._overview_no_llm_fallback(
                query, reason, evaluation_mode=evaluation_mode
            )

        retrieval = await self.statutes.retrieve(entities, query=query)
        sections = retrieval.sections

        return (
            _compose_answer(
                Route.RAG,
                sections,
                reason,
                evaluation_mode=evaluation_mode,
                overview_mode=overview_mode,
            ),
            sections,
            [],
        )

    async def _overview_no_llm_fallback(
        self,
        query: str,
        reason: str,
        *,
        evaluation_mode: bool,
    ) -> tuple[str, list[SectionResult], list[dict]]:
        """LLM-down recovery path for overview queries.

        The earlier RAG attempt either raised (rate limit, missing key,
        network error) or returned no sources. In overview mode we
        already have a deterministic fallback that does NOT need the
        LLM: pull the act-wide sample via ``hybrid_retrieve`` and run
        it through :func:`_compose_overview_answer`. The user sees a
        grounded "Primary legal source / Major areas covered" message
        instead of a confused "not indexed" claim about an act we
        actually carry.

        Three terminal sub-cases when retrieval still returns nothing:

        1. Act not resolved (rewrite found no act_key) → "specify a
           recognised act + here's what we carry".
        2. Act resolved + registered but NOT indexed → "supported but
           not currently indexed". Genuine operator drift.
        3. Act resolved + indexed but the sample came back empty →
           "transient retrieval issue; try again". This used to
           misroute through case 3 of the previous logic and
           incorrectly claim "not indexed".
        """
        from app.rag.query_rewrite import rewrite_query
        from app.rag.retrieval import retrieve as hybrid_retrieve
        from app.services.act_registry import ACT_REGISTRY
        from app.services.corpus_status import (
            get_corpus_status,
            supported_acts_brief,
        )

        result = await hybrid_retrieve(query, overview_mode=True)
        if result.chunks:
            sections = [self._chunk_to_section(c) for c in result.chunks]
            chunks = [_chunk_to_record(c) for c in result.chunks]
            answer = _compose_overview_answer(sections)
            return answer, sections, chunks

        # No chunks came back. Diagnose which case it is and produce
        # the honest message.
        requested = rewrite_query(query).act_keys
        status = await get_corpus_status()
        listed = _format_act_list(supported_acts_brief(), max_items=30)

        if not requested:
            # Case 1 — couldn't even identify which Act.
            message = (
                "**I couldn't identify which Act you'd like an "
                "overview of.**\n\n"
                f"Available legal sources right now: {listed}. Ask "
                "for an overview of any of these by name (e.g. "
                "*“Tell me about the Motor Vehicles Act”*), or cite a "
                "specific section for a precise lookup."
            )
            return message, [], []

        registered_but_missing = [
            k for k in requested
            if k in status.supported_keys and k not in status.indexed_keys
        ]
        if registered_but_missing:
            # Case 2 — genuine drift: supported but not indexed.
            missing_names = ", ".join(
                ACT_REGISTRY[k].name for k in registered_but_missing
            )
            message = (
                f"**{missing_names} is supported by LawFlow but is "
                "not currently indexed in this deployment.**\n\n"
                "An operator should re-run corpus ingestion. In the "
                f"meantime, you can ask about: {listed}."
            )
            return message, [], []

        # Case 3 — act is indexed but the sample came back empty.
        # This is a transient retrieval issue, NOT a corpus problem.
        # Honesty matters here: name the act, acknowledge the issue,
        # don't fall back to "not indexed".
        indexed_names = ", ".join(
            ACT_REGISTRY[k].name for k in requested if k in status.indexed_keys
        ) or "this Act"
        message = (
            f"**Retrieval returned no passages for {indexed_names} "
            "right now, although the corpus is indexed.**\n\n"
            "This usually clears on a retry. If it persists, the admin "
            "System Health page will show the active-chunk count for "
            f"each act. In the meantime you can ask about: {listed}."
        )
        return message, [], []

    async def _rag_invoke(
        self,
        query: str,
        *,
        evaluation_mode: bool = False,
        overview_mode: bool = False,
    ):
        """Dispatch RAG generation to either the native engine or the
        opt-in LangGraph pipeline. ``overview_mode`` propagates to the
        native engine; the LangGraph path currently doesn't carry it
        (would require a graph-state addition), so when overview is
        requested we always use the native engine to keep behaviour
        consistent.
        """
        from app.integrations.lc import lc_settings

        if lc_settings.use_langgraph_rag and not overview_mode:
            try:
                from app.graphs.rag_graph import graph_answer

                return await graph_answer(query, evaluation_mode=evaluation_mode)
            except Exception as exc:  # noqa: BLE001 — boundary
                logger.warning(
                    "LangGraph RAG unavailable (%s: %s) — using native engine",
                    type(exc).__name__,
                    exc,
                )
        return await self.rag.answer(
            query,
            evaluation_mode=evaluation_mode,
            overview_mode=overview_mode,
        )

    @traced(name="legal_service.process_query", run_type="chain")
    async def process_query(
        self,
        query: str,
        session_id: str | None = None,
        *,
        evaluation_mode: bool = False,
    ) -> dict:
        """Public entry point.

        ``evaluation_mode=True`` swaps the prompt + composer to the
        terse benchmark variant. ONLY the evaluation pipeline calls
        this with the flag set — see
        :class:`app.evaluation.service.EvaluationService._run_one`.
        The chat surface, ``/api/v1/query``, and the streaming endpoint
        leave it default-False.
        """
        async with metrics.timer("process_query_ms"):
            return await self._process_query(
                query, session_id, evaluation_mode=evaluation_mode
            )

    async def _process_query(
        self,
        query: str,
        session_id: str | None = None,
        *,
        evaluation_mode: bool = False,
    ) -> dict:
        # Multi-turn memory: resolve subjectless follow-ups against the
        # remembered legal anchor ("What is the punishment?" → "...
        # regarding Section 420 IPC"). The user still sees their original
        # query; only the effective query drives routing/retrieval.
        effective_query, followup_note = conversation_memory.resolve(
            session_id, query
        )

        classification, extraction = await asyncio.gather(
            self.classifier.classify(effective_query),
            self.extractor.extract(effective_query),
        )
        routing = await self.router.decide(
            intent=classification.intent,
            entities=extraction.entities,
        )

        route = routing.route
        reason = routing.reason
        if followup_note:
            reason = f"{reason} · {followup_note}"

        # Observability: tag the trace with the deterministic routing
        # decision so LangSmith filters/dashboards work ("show all RAG
        # queries", "latency for deterministic vs RAG", etc.). No-op when
        # tracing is disabled.
        set_run_metadata(
            session_id=session_id,
            route=str(route),
            intent=classification.intent,
            confidence=float(classification.confidence),
            followup=bool(followup_note),
            n_entities=len(extraction.entities),
        )
        # In-process metrics — counters for routes/intents and a sample of
        # followup-vs-fresh ratio. Latency is captured by the outer timer.
        metrics.inc("queries_total")
        metrics.inc("queries_by_route", route=str(route))
        metrics.inc("queries_by_intent", intent=classification.intent)
        if followup_note:
            metrics.inc("followup_queries")

        ent_dicts = [
            {"type": e.type, "value": e.value} for e in extraction.entities
        ]
        act_keys: list[str] = []
        for e in extraction.entities:
            if e.type == "ACT":
                k = resolve_act(e.value)
                if k and k not in act_keys:
                    act_keys.append(k)
        ctx = legal_context(
            act_keys,
            effective_query,
            intent=classification.intent,
            route=str(route),
        )
        subject = build_subject(ent_dicts)

        def _remember(intent: str, rt: str) -> None:
            # Only substantive (legal) turns occupy the bounded memory
            # window. Greetings / non-legal chatter carry no legal anchor
            # and nothing consumes them — recording them would evict the
            # last real legal subject during mixed legal+casual dialogue.
            if rt in (Route.CONVERSATION, Route.UNKNOWN):
                return
            conversation_memory.record(
                session_id,
                Turn(
                    query=query,
                    intent=intent,
                    route=str(rt),
                    subject=subject,
                    domain=ctx["domain"],
                    entities=ent_dicts,
                ),
            )

        statute_sections: list[SectionResult] = []
        retrieved_chunks: list[dict] = []
        answer: str | None = None

        # Conversation / unknown — reply directly. NO retrieval, NO RAG,
        # NO vector store: casual or non-legal input must never surface
        # legal provisions.
        if route in (Route.CONVERSATION, Route.UNKNOWN):
            _remember(classification.intent, route)
            # Eval mode never wants the friendly canned reply — the
            # benchmark CSV only contains legal questions, so a
            # conversational route here is a routing miss; the eval
            # answer should be the terse no-provision marker so the
            # scorer sees a clean zero.
            conv_answer = (
                "No relevant provision in the corpus."
                if evaluation_mode
                else _conversational_answer(query, route)
            )
            return {
                "query":            query,
                "answer":           conv_answer,
                "intent":           classification.intent,
                "confidence":       classification.confidence,
                "entities":         extraction.entities,
                "route":            route,
                "reason":           reason,
                "statute_sections": [],
                # Greetings/non-legal: no domain, no suggestions surfaced.
                "domain":           None,
                "related_acts":     [],
                "suggestions":      [],
                "help_text":        None,
                "next_actions":     [],
                "examples":         [],
                "retrieved_chunks": [],
            }

        # Deterministic route — exact statute/article entity lookup only.
        # primary_only returns just the single best match (no cross-act
        # duplicates) and no query is passed, so an explicit statute query
        # never broadens into keyword/semantic results.
        if route == Route.DETERMINISTIC:
            retrieval = await self.statutes.retrieve(
                extraction.entities, primary_only=True
            )
            statute_sections = retrieval.sections
            # Always compose deterministically here — even on a miss the
            # response is an honest "exact provision not found" message
            # rather than degrading an explicit statute query into broad
            # semantic RAG (which surfaced unrelated provisions).
            answer = _compose_answer(
                Route.DETERMINISTIC,
                statute_sections,
                reason,
                evaluation_mode=evaluation_mode,
            )

        # RAG route — semantic retrieval + Groq generation, with a graceful
        # deterministic-composition fallback if generation is unavailable.
        if route == Route.RAG and answer is None:
            # Broad informational intent ("tell me about MV Act") flips
            # the retrieval substrate + generation prompt to overview
            # mode. The orchestrator falls back to normal hybrid if no
            # act resolves, so this is safe even on borderline queries.
            overview_mode = classification.intent == "legal_overview"
            answer, statute_sections, retrieved_chunks = await self._rag_answer(
                effective_query,
                extraction.entities,
                reason,
                evaluation_mode=evaluation_mode,
                overview_mode=overview_mode,
            )

        # Fix A — authoritative anchoring. Entity-derived act_keys/subject
        # are lossy for bare-code queries ("IPC 420" prunes the ACT token
        # in span-overlap). The *resolved* provision carries the true act,
        # so prefer it for the memory anchor and right-rail context. Falls
        # back to the entity/topic-derived values on a miss.
        if statute_sections:
            sec_keys: list[str] = []
            for s in statute_sections:
                k = act_key_for_name(s.act)
                if k and k not in sec_keys:
                    sec_keys.append(k)
            if sec_keys:
                act_keys = sec_keys
                ctx = legal_context(
                    act_keys,
                    effective_query,
                    intent=classification.intent,
                    route=str(route),
                )
            subject = _subject_from_sections(statute_sections) or subject

        _remember(classification.intent, route)
        # Observability: surface answer-shape metrics on the trace so
        # LangSmith dashboards can report sections-per-query, empty-answer
        # rate, etc. without re-reading the response.
        set_run_outputs(
            n_sections=len(statute_sections),
            answer_chars=len(answer or ""),
            domain=ctx["domain"],
            route=str(route),
        )
        return {
            "query":            query,
            "answer":           answer or "",
            "intent":           classification.intent,
            "confidence":       classification.confidence,
            "entities":         extraction.entities,
            "route":            route,
            "reason":           reason,
            "statute_sections": statute_sections,
            # Dynamic right-rail context (additive — schema preserved).
            "domain":           ctx["domain"],
            "related_acts":     ctx["related_acts"],
            "suggestions":      ctx["suggestions"],
            "help_text":        ctx.get("help_text"),
            "next_actions":     ctx.get("next_actions", []),
            "examples":         ctx.get("examples", []),
            # Per-chunk retrieval explainability — only populated on the RAG
            # path (deterministic route doesn't run vector retrieval). Empty
            # otherwise so older API clients see a known-empty array, not
            # `null`. See app/services/streaming.py for SSE wiring.
            "retrieved_chunks": retrieved_chunks,
        }
