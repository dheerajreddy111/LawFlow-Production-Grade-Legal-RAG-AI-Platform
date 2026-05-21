"""LangChain / LangSmith / LangGraph integration layer.

Everything here is **optional**. The package imports cleanly even when
the LangChain stack is uninstalled or when no LangSmith key is set;
the rest of LawFlow does not depend on this module being importable.

Public surface:

- :func:`is_tracing_enabled` — runtime check (env-driven)
- :func:`get_callbacks` — list of LangChain callback handlers to attach
  to runnables; empty list when tracing is disabled
- :func:`run_metadata` — common metadata block to tag a single
  ``LegalService.process_query`` invocation (session_id, route, intent…)

Submodules:

- ``settings``   env-driven configuration (LangSmith project, tags, …)
- ``tracing``    LangSmith tracing setup + lifecycle helpers
- ``providers``  LangChain ``ChatAnthropic`` / ``ChatGroq`` wrappers that
                 satisfy the existing :class:`app.rag.engine.LLMProvider`
                 protocol (Phase 2)
- ``retriever``  LangChain ``BaseRetriever`` over the existing
                 :class:`app.rag.vector_store.VectorStore` (Phase 2)
- ``prompts``    ``ChatPromptTemplate`` for the static RAG system prompt
                 + numbered-context user prompt (Phase 2)
- ``structured`` Pydantic schemas + parsers for citation validation
                 (used inside the LangGraph RAG graph) (Phase 2)
"""

from app.integrations.lc.observability import (
    set_run_metadata,
    set_run_outputs,
    traced,
)
from app.integrations.lc.settings import (
    LCSettings,
    is_tracing_enabled,
    lc_settings,
)
from app.integrations.lc.tracing import (
    configure_langsmith,
    connectivity_status,
    get_callbacks,
    run_metadata,
)

__all__ = [
    "LCSettings",
    "lc_settings",
    "is_tracing_enabled",
    "configure_langsmith",
    "connectivity_status",
    "get_callbacks",
    "run_metadata",
    "traced",
    "set_run_metadata",
    "set_run_outputs",
]
