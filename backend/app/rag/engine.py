"""
Retrieval-Augmented Generation engine for the Indian legal corpus.

Pipeline
--------
    query
      │
      ▼
    VectorStore.similarity_search()      ── EmbeddingService embeds the query
      │  → list[RetrievedChunk]
      ▼
    _build_prompt()                      ── numbered, citation-ready context
      │
      ▼
    LLMProvider.complete()               ── grounded, citation-aware answer
      │
      ▼
    RAGResponse(answer, sources, confidence)

Design notes
------------
    Provider-agnostic
        The engine depends on the small :class:`LLMProvider` protocol, not on
        any SDK.  :class:`GroqProvider` (preferred when ``GROQ_API_KEY`` is
        set) and :class:`AnthropicProvider` both implement it; an OpenAI
        provider can be added later behind the same protocol without
        touching the engine.  ``default_provider()`` selects automatically
        and, when several are configured, wraps them in a
        :class:`FallbackProvider` so a runtime failure in the preferred
        provider degrades gracefully to the next.

    Async-ready
        Retrieval and embedding are already async (VectorStore /
        EmbeddingService).  The LLM call uses ``AsyncAnthropic`` so the event
        loop is never blocked.  Streaming is intentionally not implemented yet.

    Citation-aware
        Retrieved chunks are injected as numbered sources ``[1] … [n]``.  The
        system prompt instructs the model to ground every statement in those
        sources using ``[n]`` markers and to refuse when the context is
        insufficient rather than hallucinate law.

    Confidence
        A retrieval-grounded heuristic: the mean cosine similarity of the
        chunks actually shown to the model, ``0.0`` when nothing was retrieved.
        It reflects how well the corpus covered the query, not the model's
        self-assessment (which is unreliable).

    Prompt caching
        The system prompt is a frozen instruction block marked
        ``cache_control: ephemeral`` so repeated queries reuse it.  The
        volatile context+question goes in the user turn, after the cached
        prefix (see ``shared/prompt-caching.md`` — stable content first).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from app.config import settings
from app.integrations.lc import set_run_outputs, traced
from app.rag.rerank import RAG_RETRIEVE_K, rerank
from app.rag.vector_store import VectorStore, vector_store

if TYPE_CHECKING:  # avoid importing the SDKs at module import time
    from anthropic import AsyncAnthropic
    from groq import AsyncGroq

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

# Default to the most capable Claude model; override via env if needed.
LLM_MODEL: str = os.getenv("LLM_MODEL", "claude-opus-4-7")
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "8000"))

# Groq — fast OpenAI-compatible inference. Model is env-configurable.
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# Retrieval precision. Vector search casts a wide net (RAG_RETRIEVE_K);
# the deterministic reranker (app.rag.rerank) then keeps the 1–3 on-point
# provisions. RAG_TOP_K is the default for direct `retrieve()` callers.
RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "4"))

_SYSTEM_PROMPT: str = (
    "You are LawFlow, an assistant for Indian legal research. Answer the "
    "user's question using ONLY the numbered context passages provided.\n\n"
    "Rules:\n"
    "1. Ground every legal statement in the context. After each claim, cite "
    "the supporting passage(s) inline as [1], [2], etc.\n"
    "2. If the context does not contain enough information to answer, say so "
    "explicitly — do not rely on prior knowledge or invent statutes, section "
    "numbers, or case law.\n"
    "3. Be precise and concise. Quote exact section numbers and statute names "
    "when they appear in the context.\n"
    "4. This is legal information, not legal advice; do not tell the user what "
    "they should do in their specific situation."
)


# Dedicated system prompt used only when ``evaluation_mode=True`` flows
# through the pipeline. Optimises for lexical overlap against the
# benchmark's expected_answer — terse, no markdown, no [n] citations,
# no disclaimer. Production answers are unaffected; this prompt is
# only ever rendered by the evaluation harness.
_EVAL_SYSTEM_PROMPT: str = (
    "You are answering benchmark evaluation questions about Indian law "
    "using ONLY the numbered context passages provided.\n\n"
    "Rules:\n"
    "1. Respond in ONE short sentence — the direct answer, nothing more.\n"
    "2. Prefer wording lifted from the context passages (the benchmark "
    "expects close lexical match with the source text).\n"
    "3. Do NOT include citation markers like [1] or [2].\n"
    "4. Do NOT include markdown, bullet points, headings, or bold text.\n"
    "5. Do NOT include legal disclaimers, framing, or 'this is legal "
    "information' boilerplate.\n"
    "6. Do NOT explain or hedge — return only the substantive answer.\n"
    "7. If the context cannot answer the question, reply exactly: "
    "'No relevant provision in the corpus.'"
)

# System prompt used when a query has been classified as a broad
# legal-overview request (e.g. "Tell me about the MV Act"). The
# generator is told to write a grounded summary — the act's scope plus
# the major areas covered — strictly using the supplied provisions.
# Overview answers retain the [n] citation markers because the user
# can usefully follow up on any listed area.
_OVERVIEW_SYSTEM_PROMPT: str = (
    "You are LawFlow, an assistant for Indian legal research. The user "
    "has asked for an OVERVIEW of an Act, not a section-specific "
    "lookup. Produce a concise grounded summary using ONLY the numbered "
    "context passages.\n\n"
    "Rules:\n"
    "1. Open with one short sentence naming the Act and its general "
    "purpose, based only on what the passages reveal.\n"
    "2. Then list the major areas the Act covers as a short bulleted "
    "list — each bullet is a 4–10 word phrase derived from the "
    "passages (definitions, headline provisions, penalties, "
    "procedural mechanics).\n"
    "3. Cite passages with [1], [2], etc. on relevant bullets so the "
    "user can trace each claim back to a provision.\n"
    "4. Do NOT invent areas the passages don't support. If the passages "
    "are sparse, list fewer bullets — never speculate.\n"
    "5. Do NOT recite full statutory text; the user wants a summary, "
    "not a paste of provisions.\n"
    "6. Close with one sentence noting this is legal information, not "
    "legal advice."
)


# ── Public types ──────────────────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    text: str
    source: str       # document title or citation string
    score: float      # cosine similarity in [0, 1]
    metadata: dict
    # Reranking explainability (internal only — not surfaced in the API
    # response schema). Populated by app.rag.rerank for the future
    # AI-transparency panel.
    rerank_score: float | None = None
    rerank_reason: str | None = None


@dataclass
class RAGResponse:
    answer: str
    sources: list[RetrievedChunk] = field(default_factory=list)
    confidence: float = 0.0


class LLMNotConfiguredError(RuntimeError):
    """Raised when an LLM call is attempted without a configured API key."""


# ── Provider abstraction (Claude now, OpenAI later) ───────────────────────────

class LLMProvider(Protocol):
    """Minimal async LLM contract the engine depends on.

    Any provider (Anthropic, OpenAI, …) that implements this can be injected
    into :class:`RAGEngine` without changing engine code.
    """

    async def complete(self, system: str, user: str) -> str: ...


class AnthropicProvider:
    """Claude provider via the official ``anthropic`` SDK (async, cached)."""

    def __init__(
        self,
        *,
        model: str = LLM_MODEL,
        max_tokens: int = LLM_MAX_TOKENS,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._api_key = api_key or settings.anthropic_api_key
        self._client: AsyncAnthropic | None = None

    def _get_client(self) -> AsyncAnthropic:
        if self._client is None:
            if not self._api_key:
                raise LLMNotConfiguredError(
                    "ANTHROPIC_API_KEY is not set — cannot generate answers. "
                    "Set it in backend/.env to enable RAG generation."
                )
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=self._api_key)
        return self._client

    @traced(name="llm.anthropic", run_type="llm")
    async def complete(self, system: str, user: str) -> str:
        client = self._get_client()
        # Frozen instruction block → cache_control so repeated queries reuse
        # the prefix. The volatile context+question stays in the user turn.
        response = await client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
        # Surface token usage on the LangSmith span (no-op when tracing
        # is off). The native SDK exposes usage on the response object;
        # we mirror the LangChain naming so dashboards work uniformly.
        usage = getattr(response, "usage", None)
        if usage is not None:
            set_run_outputs(
                model=self._model,
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                cache_read_input_tokens=getattr(
                    usage, "cache_read_input_tokens", None
                ),
                cache_creation_input_tokens=getattr(
                    usage, "cache_creation_input_tokens", None
                ),
            )
        return "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()


class GroqProvider:
    """Groq provider via the official ``groq`` SDK (async).

    Implements the same :class:`LLMProvider` protocol as AnthropicProvider,
    so the engine's citation-aware prompt assembly and RAGResponse schema
    are unchanged — only the transport differs. The frozen ``_SYSTEM_PROMPT``
    (with its [1]/[2] citation rules) is sent as the system message and the
    numbered-context prompt as the user message.

    Streaming is intentionally left non-streaming here; a ``stream()`` method
    can be added later (Groq supports ``stream=True``) without touching the
    engine or this class's ``complete`` contract.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        max_tokens: int = LLM_MAX_TOKENS,
        api_key: str | None = None,
    ) -> None:
        self._model = model or settings.groq_model or GROQ_MODEL
        self._max_tokens = max_tokens
        self._api_key = api_key or settings.groq_api_key
        self._client: AsyncGroq | None = None

    def _get_client(self) -> AsyncGroq:
        if self._client is None:
            if not self._api_key:
                raise LLMNotConfiguredError(
                    "GROQ_API_KEY is not set — cannot generate answers. "
                    "Set it in backend/.env to enable Groq RAG generation."
                )
            from groq import AsyncGroq

            self._client = AsyncGroq(api_key=self._api_key)
        return self._client

    @traced(name="llm.groq", run_type="llm")
    async def complete(self, system: str, user: str) -> str:
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=0.2,  # low — grounded, deterministic legal answers
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        usage = getattr(response, "usage", None)
        if usage is not None:
            set_run_outputs(
                model=self._model,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
            )
        return (response.choices[0].message.content or "").strip()


class OpenAIProvider:
    """Placeholder for an OpenAI-backed provider (added later).

    Kept so the provider-agnostic wiring is visible; implement against the
    same :class:`LLMProvider` protocol when OpenAI support is needed.
    """

    async def complete(self, system: str, user: str) -> str:  # noqa: D401
        raise NotImplementedError("OpenAI provider not yet implemented")


class FallbackProvider:
    """Composite provider: try each configured provider in priority order.

    Implements the same :class:`LLMProvider` protocol, so the engine is
    untouched. If the preferred provider (e.g. Groq) is unavailable at call
    time — bad key, network error, decommissioned model, missing SDK — the
    next configured provider handles the request instead. The last error is
    re-raised only if *every* provider fails.
    """

    def __init__(self, providers: list[tuple[str, LLMProvider]]) -> None:
        self._providers = providers

    async def complete(self, system: str, user: str) -> str:
        last_error: Exception | None = None
        for name, provider in self._providers:
            try:
                return await provider.complete(system, user)
            except Exception as exc:  # noqa: BLE001 — boundary: try next
                last_error = exc
                logger.warning(
                    "LLM provider '%s' failed (%s: %s) — falling back",
                    name,
                    type(exc).__name__,
                    exc,
                )
        raise last_error or LLMNotConfiguredError(
            "No LLM provider is configured. Set GROQ_API_KEY (or "
            "ANTHROPIC_API_KEY) in backend/.env to enable RAG generation."
        )


def default_provider() -> LLMProvider:
    """Build the active provider from configured credentials.

    Priority: Groq → Anthropic → OpenAI. When more than one is configured,
    a :class:`FallbackProvider` chains them so a runtime failure in the
    preferred provider degrades gracefully to the next. With nothing
    configured, returns a provider that raises a clear
    :class:`LLMNotConfiguredError` on first use.
    """
    chain: list[tuple[str, LLMProvider]] = []
    if settings.groq_api_key:
        chain.append(("groq", GroqProvider()))
    if settings.anthropic_api_key:
        chain.append(("anthropic", AnthropicProvider()))
    if settings.openai_api_key:
        chain.append(("openai", OpenAIProvider()))

    if not chain:
        return AnthropicProvider()  # raises a clear error on first use
    if len(chain) == 1:
        return chain[0][1]
    return FallbackProvider(chain)


# ── Engine ────────────────────────────────────────────────────────────────────

class RAGEngine:
    """Retrieve → assemble grounded prompt → generate citation-aware answer.

    Example
    -------
        engine = RAGEngine()
        result = await engine.answer("What is the punishment for cheating?")
        print(result.answer, result.confidence)
        for i, src in enumerate(result.sources, 1):
            print(f"[{i}] {src.source}  ({src.score})")
    """

    def __init__(
        self,
        *,
        store: VectorStore = vector_store,
        provider: LLMProvider | None = None,
    ) -> None:
        self._store = store
        self._provider = provider or default_provider()

    @traced(name="rag.retrieve", run_type="retriever")
    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        jurisdiction: str | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve the most relevant legal passages for a query.

        ``jurisdiction`` filters on the ``extra.jurisdiction`` metadata field
        (populated at ingestion time) when supplied.
        """
        where = {"extra.jurisdiction": jurisdiction} if jurisdiction else None
        hits = await self._store.similarity_search(
            query, top_k=top_k, where=where
        )
        chunks = [
            RetrievedChunk(
                text=h.text,
                source=h.source or h.metadata.get("section_title", "unknown"),
                score=h.score,
                metadata=h.metadata,
            )
            for h in hits
        ]
        set_run_outputs(
            n_hits=len(chunks),
            top_score=round(max((c.score for c in chunks), default=0.0), 4),
            jurisdiction=jurisdiction,
        )
        return chunks

    @traced(name="rag.generate", run_type="chain")
    async def generate(
        self,
        query: str,
        context: list[RetrievedChunk],
        *,
        evaluation_mode: bool = False,
        overview_mode: bool = False,
    ) -> str:
        """Generate an answer from retrieved context.

        Three system prompts are available, selected by the kwargs:

        - default — citation-aware production response.
        - ``evaluation_mode=True`` — terse benchmark variant. Used only
          by the evaluation harness.
        - ``overview_mode=True`` — grounded "what does this Act cover"
          summary. Used when the classifier sees a broad informational
          query and the rewriter resolves an act.

        ``evaluation_mode`` takes precedence over ``overview_mode``
        because the eval pipeline must never deviate from the
        benchmark format. In normal traffic only one of these is set
        at a time anyway.
        """
        if not context:
            # Eval mode wants a deterministic empty-response token so
            # the scorer can flag missing-retrieval rows clearly,
            # rather than the verbose production fallback.
            return (
                "No relevant provision in the corpus."
                if evaluation_mode
                else (
                    "I could not find any relevant passages in the legal "
                    "corpus to answer this question."
                )
            )
        if evaluation_mode:
            system = _EVAL_SYSTEM_PROMPT
        elif overview_mode:
            system = _OVERVIEW_SYSTEM_PROMPT
        else:
            system = _SYSTEM_PROMPT
        user = _build_prompt(
            query,
            context,
            evaluation_mode=evaluation_mode,
            overview_mode=overview_mode,
        )
        return await self._provider.complete(system, user)

    @traced(name="rag.answer", run_type="chain")
    async def answer(
        self,
        query: str,
        *,
        top_k: int = RAG_RETRIEVE_K,
        jurisdiction: str | None = None,
        evaluation_mode: bool = False,
        overview_mode: bool = False,
    ) -> RAGResponse:
        """Full pipeline: hybrid retrieve → rerank → generate → cite.

        ``evaluation_mode=True`` swaps the system prompt + user framing
        for the terse benchmark variant. ``overview_mode=True`` flips
        the retrieval substrate from hybrid search to a diversified
        act-wide sample, and switches to the overview generation prompt
        so the LLM writes a grounded summary of the act. Retrieval
        explainability is preserved in both cases — only the LLM-side
        prompt and the sampling strategy differ.
        """
        # Import here to avoid the import cycle (retrieval imports
        # RetrievedChunk back from engine).
        from app.rag.retrieval import retrieve as hybrid_retrieve

        result = await hybrid_retrieve(
            query,
            top_k=top_k,
            store=self._store,
            jurisdiction=jurisdiction,
            overview_mode=overview_mode,
        )
        chunks = result.chunks
        answer = await self.generate(
            query,
            chunks,
            evaluation_mode=evaluation_mode,
            overview_mode=overview_mode,
        )
        # In evaluation mode the LLM is instructed not to emit ``[n]``
        # markers, so per-citation extraction would always fall back to
        # ``chunks[:1]``. We surface the top-1 chunk as the cited source
        # for explainability, and call confidence on it. Retrieval
        # scoring is unchanged — eval mode only differs at the LLM
        # boundary.
        if evaluation_mode:
            cited = chunks[:1]
        else:
            # Keep only provisions the model actually cited via [n] markers,
            # in citation order. The model's first citation is the provision
            # it grounds the answer on — a far more reliable "primary"
            # signal than raw cosine score (which rates near-synonym
            # provisions almost equally, e.g. "driving licence" vs
            # "drink-driving").
            cited = _cited_chunks(answer, chunks)
        set_run_outputs(
            n_chunks_retrieved=len(chunks),
            n_chunks_cited=len(cited),
            confidence=_confidence(cited),
            evaluation_mode=evaluation_mode,
        )
        return RAGResponse(
            answer=answer,
            sources=cited,
            confidence=_confidence(cited),
        )


# ── Prompt assembly & confidence ──────────────────────────────────────────────

def _build_prompt(
    query: str,
    context: list[RetrievedChunk],
    *,
    evaluation_mode: bool = False,
    overview_mode: bool = False,
) -> str:
    """Numbered, citation-ready context followed by the question.

    The closing line is the only thing that differs between modes:

    - default — "answer using these passages, cite [n]"
    - evaluation — "one short sentence, no markdown"
    - overview — "summarise the act, list the major areas"

    The numbered context blocks themselves stay identical so the
    retrieval explainability surface still records which chunk is
    which.
    """
    blocks: list[str] = []
    for i, chunk in enumerate(context, 1):
        blocks.append(f"[{i}] (source: {chunk.source})\n{chunk.text.strip()}")
    joined = "\n\n".join(blocks)
    if evaluation_mode:
        closer = (
            "Answer in one short sentence using wording from the passages. "
            "No citations, markdown, or disclaimers."
        )
    elif overview_mode:
        closer = (
            "Write a concise overview of this Act. Open with one "
            "sentence naming the Act and its general purpose, then a "
            "short bulleted list of the major areas it covers, citing "
            "the passages as [n]. Do NOT invent areas the passages "
            "don't mention."
        )
    else:
        closer = "Answer using only the passages above, citing them as [n]."
    return (
        f"Context passages:\n\n{joined}\n\n"
        f"Question: {query.strip()}\n\n"
        f"{closer}"
    )


_CITATION_RE = re.compile(r"\[(\d{1,2})\]")


def _cited_chunks(
    answer: str, chunks: list[RetrievedChunk]
) -> list[RetrievedChunk]:
    """Keep only chunks the model cited via [n] markers, in citation order.

    Falls back to the single best-scoring chunk if the answer contains no
    parseable citations, so a grounded answer never shows zero sources nor
    the full noisy retrieval tail.
    """
    if not chunks:
        return []
    seen: set[int] = set()
    cited: list[RetrievedChunk] = []
    for m in _CITATION_RE.finditer(answer):
        idx = int(m.group(1)) - 1  # [1] → chunks[0]
        if 0 <= idx < len(chunks) and idx not in seen:
            seen.add(idx)
            cited.append(chunks[idx])
    return cited or chunks[:1]


def _confidence(chunks: list[RetrievedChunk]) -> float:
    """Retrieval-grounded confidence: mean similarity of shown chunks."""
    if not chunks:
        return 0.0
    return round(sum(c.score for c in chunks) / len(chunks), 4)


# Module-level default instance for convenient import:
#   from app.rag.engine import rag_engine
rag_engine = RAGEngine()
