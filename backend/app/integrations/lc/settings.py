"""Environment-driven configuration for the LangChain / LangSmith layer.

Design
------
All knobs are read from env at import time so they are visible in one
place. None of the fields are required: when no LangSmith key is set,
:func:`is_tracing_enabled` returns ``False`` and the rest of the
integration becomes a no-op.

Env vars
--------
- ``LANGCHAIN_TRACING_V2``  ``"true"`` enables LangSmith tracing
- ``LANGCHAIN_API_KEY``     LangSmith API key (required when tracing on)
- ``LANGCHAIN_PROJECT``     LangSmith project name (default: ``lawflow``)
- ``LANGCHAIN_ENDPOINT``    custom LangSmith endpoint (optional)
- ``RAG_USE_LANGGRAPH``     ``"true"`` routes RAG queries through the
                            LangGraph graph (Phase 4 — default off)
- ``LC_DEFAULT_TAGS``       comma-separated tags applied to every trace
                            (default: ``lawflow,backend``)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return ["lawflow", "backend"]
    return [t.strip() for t in raw.split(",") if t.strip()]


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class LCSettings:
    """Immutable snapshot of LangChain/LangSmith env at import time."""

    tracing_enabled: bool = field(
        default_factory=lambda: _bool("LANGCHAIN_TRACING_V2")
    )
    api_key: str | None = field(
        default_factory=lambda: os.getenv("LANGCHAIN_API_KEY") or None
    )
    project: str = field(
        default_factory=lambda: os.getenv("LANGCHAIN_PROJECT", "lawflow")
    )
    endpoint: str | None = field(
        default_factory=lambda: os.getenv("LANGCHAIN_ENDPOINT") or None
    )
    use_langgraph_rag: bool = field(
        default_factory=lambda: _bool("RAG_USE_LANGGRAPH")
    )
    default_tags: list[str] = field(
        default_factory=lambda: _parse_tags(os.getenv("LC_DEFAULT_TAGS"))
    )


lc_settings = LCSettings()


def is_tracing_enabled() -> bool:
    """True iff LangSmith tracing is on AND an API key is available.

    Both conditions are required: a stray ``LANGCHAIN_TRACING_V2=true``
    without a key would log noisy errors from the LangSmith client on
    every call. Treat that case as "off" rather than half-on.
    """
    return bool(lc_settings.tracing_enabled and lc_settings.api_key)
