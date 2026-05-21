"""LangChain-backed LLM providers that satisfy LawFlow's existing protocol.

These classes implement :class:`app.rag.engine.LLMProvider` (``async
complete(system, user) -> str``), so they slot into
:class:`app.rag.engine.RAGEngine` without changing engine code, and
into :class:`app.rag.engine.FallbackProvider` alongside the native
``AnthropicProvider`` / ``GroqProvider``.

Why offer this when the native providers already work?
------------------------------------------------------
1. **Automatic LangSmith tracing.** Calls through these wrappers show
   up in LangSmith with full prompt, response, token counts and
   latency — no extra instrumentation in :class:`RAGEngine`.
2. **Drop-in inside the LangGraph RAG graph.** The graph composes
   runnables; using a LangChain chat model is the natural fit there.
3. **No replacement of the originals.** The native providers stay
   primary in :func:`app.rag.engine.default_provider` so behaviour is
   unchanged unless someone explicitly opts in (Phase 4 sets the graph
   to use these; the synchronous RAG path is unaffected).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import settings
from app.integrations.lc.tracing import get_callbacks
from app.rag.engine import GROQ_MODEL, LLM_MAX_TOKENS, LLM_MODEL

if TYPE_CHECKING:
    from langchain_anthropic import ChatAnthropic
    from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)


# ── Anthropic ────────────────────────────────────────────────────────────────

class LangChainAnthropicProvider:
    """LawFlow ``LLMProvider`` backed by ``langchain_anthropic.ChatAnthropic``.

    Behaviour parity with :class:`app.rag.engine.AnthropicProvider`:
    same default model, same max-tokens, system prompt + user message
    structure. Prompt caching is not configured here — the
    :class:`langchain_anthropic.ChatAnthropic` wrapper does not expose
    ``cache_control`` per system block in a stable way across versions,
    so the native :class:`AnthropicProvider` remains the cache-aware
    path used by the synchronous RAG pipeline.
    """

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
        self._client: ChatAnthropic | None = None

    def _get_client(self) -> "ChatAnthropic":
        if self._client is None:
            from langchain_anthropic import ChatAnthropic

            if not self._api_key:
                from app.rag.engine import LLMNotConfiguredError

                raise LLMNotConfiguredError(
                    "ANTHROPIC_API_KEY is not set — cannot use "
                    "LangChainAnthropicProvider."
                )
            self._client = ChatAnthropic(
                model=self._model,
                max_tokens=self._max_tokens,
                anthropic_api_key=self._api_key,
            )
        return self._client

    async def complete(self, system: str, user: str) -> str:
        client = self._get_client()
        callbacks = get_callbacks()
        config = {"callbacks": callbacks} if callbacks else None
        result = await client.ainvoke(
            [("system", system), ("user", user)],
            config=config,
        )
        content = getattr(result, "content", "")
        if isinstance(content, list):
            # Some models return content as a list of blocks.
            content = "".join(
                str(block.get("text", "")) if isinstance(block, dict) else str(block)
                for block in content
            )
        return (content or "").strip()


# ── Groq ─────────────────────────────────────────────────────────────────────

class LangChainGroqProvider:
    """LawFlow ``LLMProvider`` backed by ``langchain_groq.ChatGroq``.

    Parity with :class:`app.rag.engine.GroqProvider`: same model,
    same temperature (0.2 — grounded legal answers).
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
        self._client: ChatGroq | None = None

    def _get_client(self) -> "ChatGroq":
        if self._client is None:
            from langchain_groq import ChatGroq

            if not self._api_key:
                from app.rag.engine import LLMNotConfiguredError

                raise LLMNotConfiguredError(
                    "GROQ_API_KEY is not set — cannot use "
                    "LangChainGroqProvider."
                )
            self._client = ChatGroq(
                model_name=self._model,
                max_tokens=self._max_tokens,
                temperature=0.2,
                groq_api_key=self._api_key,
            )
        return self._client

    async def complete(self, system: str, user: str) -> str:
        client = self._get_client()
        callbacks = get_callbacks()
        config = {"callbacks": callbacks} if callbacks else None
        result = await client.ainvoke(
            [("system", system), ("user", user)],
            config=config,
        )
        content = getattr(result, "content", "")
        if isinstance(content, list):
            content = "".join(
                str(block.get("text", "")) if isinstance(block, dict) else str(block)
                for block in content
            )
        return (content or "").strip()


# ── Factory ──────────────────────────────────────────────────────────────────

def default_lc_provider():
    """Pick a LangChain-backed provider based on configured keys.

    Mirrors :func:`app.rag.engine.default_provider` priority order
    (Groq → Anthropic) but returns LangChain wrappers so traces include
    them. Used by the LangGraph RAG graph (Phase 4). The synchronous
    :class:`RAGEngine` keeps its own native default.
    """
    if settings.groq_api_key:
        return LangChainGroqProvider()
    if settings.anthropic_api_key:
        return LangChainAnthropicProvider()
    # Match the native default's behaviour: return one that raises a
    # clear error on first use rather than failing here.
    return LangChainAnthropicProvider()
