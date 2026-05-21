"""Observability helpers: traceable decorator + run metadata updates.

These are the *only* observability touchpoints the rest of the codebase
needs. The boundary is:

- Decorate the orchestration entry points with :func:`traced`.
- Inside a traced function, call :func:`set_run_metadata` once the
  route/intent/confidence are known so the trace is filterable.
- :func:`set_run_outputs` annotates the current span with a structured
  output payload (counts, derived metrics, …) — useful for stages that
  don't have a natural "return" to record.

When tracing is disabled (no ``LANGCHAIN_TRACING_V2`` / no API key),
:func:`traced` is the identity function and the setters are no-ops.
Nothing in the rest of the app needs to branch on enablement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from app.integrations.lc.settings import is_tracing_enabled, lc_settings

logger = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


def traced(
    name: str | None = None,
    *,
    run_type: str = "chain",
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Callable[[_F], _F]:
    """Mark a function as a LangSmith trace span.

    When tracing is **enabled**, this delegates to
    :func:`langsmith.traceable` — which threads parent/child run ids via
    contextvars so nested calls become nested spans automatically.

    When tracing is **disabled**, the decorator is an identity wrapper:
    no client import, no callback machinery, no allocations. Safe to
    sprinkle through hot code paths.

    ``run_type``: one of ``"chain" | "llm" | "tool" | "retriever" |
    "embedding" | "parser"`` — controls how LangSmith renders the span.
    """

    def decorator(fn: _F) -> _F:
        if not is_tracing_enabled():
            # No-op wrapper preserves the signature; identity is cheaper
            # than wrapping but functools.wraps is friendlier to tools.
            @wraps(fn)
            def _passthrough(*args: Any, **kwargs: Any):
                return fn(*args, **kwargs)

            return _passthrough  # type: ignore[return-value]

        try:
            from langsmith import traceable
        except Exception as exc:  # noqa: BLE001 — boundary
            logger.warning(
                "langsmith.traceable import failed (%s) — span '%s' untraced",
                exc,
                name or fn.__name__,
            )
            return fn

        all_tags = list(tags or []) + list(lc_settings.default_tags)
        return traceable(  # type: ignore[return-value]
            name=name or fn.__name__,
            run_type=run_type,  # type: ignore[arg-type]
            tags=all_tags,
            metadata=metadata or {},
        )(fn)

    return decorator


def set_run_metadata(**fields: Any) -> None:
    """Attach metadata to the *current* LangSmith run (if any).

    Use after the routing decision is made so downstream filters in
    LangSmith ("show me all RAG-routed queries") work. Silent no-op when
    tracing is off or no span is active.
    """
    if not is_tracing_enabled() or not fields:
        return
    try:
        from langsmith.run_helpers import get_current_run_tree

        run = get_current_run_tree()
        if run is None:
            return
        # `metadata` is part of `extra`; merge rather than replace.
        extra = dict(getattr(run, "extra", None) or {})
        meta = dict(extra.get("metadata") or {})
        meta.update(fields)
        extra["metadata"] = meta
        run.extra = extra
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.debug("set_run_metadata failed (%s)", exc)


def set_run_outputs(**outputs: Any) -> None:
    """Attach structured outputs to the current LangSmith run (if any).

    Useful from stages with no natural return value — e.g. annotating a
    streaming span with ``tokens_emitted=42``, ``cancelled=True``, etc.
    """
    if not is_tracing_enabled() or not outputs:
        return
    try:
        from langsmith.run_helpers import get_current_run_tree

        run = get_current_run_tree()
        if run is None:
            return
        existing = dict(getattr(run, "outputs", None) or {})
        existing.update(outputs)
        run.outputs = existing
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.debug("set_run_outputs failed (%s)", exc)
