"""LangSmith tracing setup + callback helpers.

How it works
------------
LangChain reads ``LANGCHAIN_TRACING_V2`` / ``LANGCHAIN_API_KEY`` /
``LANGCHAIN_PROJECT`` from the process environment on first use of any
runnable. We re-export those values from :mod:`.settings` so the
configuration surface is documented in one place, and we expose:

- :func:`configure_langsmith` — called once from the FastAPI lifespan;
  logs whether tracing is enabled and pushes the resolved settings back
  into ``os.environ`` so LangChain picks them up.
- :func:`get_callbacks` — returns a list of LangChain callback handlers
  to attach to runnables / chains / graphs. Empty when tracing is off
  (so passing this everywhere is safe and zero-overhead).
- :func:`run_metadata` — common ``metadata={...}`` block to tag a single
  ``LegalService.process_query`` invocation (session_id, route, intent,
  …); shows up as filterable fields in the LangSmith UI.
- :func:`trace_span` — async context manager that records a span using
  the LangSmith tracer. Useful around custom stages (route decision,
  rerank, citation validation) that aren't already LangChain runnables.

Failure mode
------------
Everything here degrades to a no-op if LangSmith is unavailable or
misconfigured. We never let observability take down the request path.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from app.integrations.lc.settings import is_tracing_enabled, lc_settings

if TYPE_CHECKING:  # avoid importing langchain at module import time
    from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


# ── One-time setup ────────────────────────────────────────────────────────────

_configured: bool = False

# Connectivity probe result, populated by `configure_langsmith` and read
# by the admin /system endpoint. Distinct from `is_tracing_enabled()` —
# tracing can be *enabled* (flag on + key set) but *unreachable* (DNS,
# firewall, expired key). We surface that to operators so they don't
# stare at an empty LangSmith project wondering where the spans went.
#
# `state` ∈ {"unknown", "ok", "error"}:
#   - "unknown": tracing disabled OR probe not yet run
#   - "ok":      probe round-tripped successfully at startup
#   - "error":   probe raised — likely bad key, network, or endpoint
# `detail` is a short human string. NEVER contains the API key.
_connectivity_state: str = "unknown"
_connectivity_detail: str | None = None


def configure_langsmith() -> bool:
    """Wire LangSmith env into ``os.environ`` and confirm import.

    Idempotent. Safe to call from the FastAPI lifespan. Returns ``True``
    when tracing was enabled, ``False`` otherwise.
    """
    global _configured, _connectivity_state, _connectivity_detail
    if _configured:
        return is_tracing_enabled()
    _configured = True

    if not is_tracing_enabled():
        logger.info("LangSmith tracing: disabled (no API key or flag off)")
        _connectivity_state = "unknown"
        _connectivity_detail = None
        return False

    # Expose to LangChain's internal env reads.
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_API_KEY", lc_settings.api_key or "")
    os.environ.setdefault("LANGCHAIN_PROJECT", lc_settings.project)
    if lc_settings.endpoint:
        os.environ.setdefault("LANGCHAIN_ENDPOINT", lc_settings.endpoint)

    try:
        # Probe the client import early so a misconfigured environment
        # surfaces at startup instead of mid-request.
        import langsmith  # noqa: F401
    except Exception as exc:  # noqa: BLE001 — boundary: never crash startup
        logger.warning(
            "LangSmith tracing requested but client import failed (%s: %s) — "
            "tracing disabled for this process",
            type(exc).__name__,
            exc,
        )
        os.environ.pop("LANGCHAIN_TRACING_V2", None)
        _connectivity_state = "error"
        _connectivity_detail = f"client import failed ({type(exc).__name__})"
        return False

    # Lightweight reachability check. ``client.info`` is the LangSmith
    # server's unauthenticated version endpoint, so this probe confirms
    # DNS + TLS + that the configured endpoint is the LangSmith API
    # (catches typo'd ``LANGCHAIN_ENDPOINT`` early) — it does NOT
    # validate the API key itself. Bad keys still surface later when
    # actual span batches are rejected; the LangSmith client logs those
    # rejections to stderr. We never log or store the key; only the
    # redacted exception type/string from a failed probe.
    try:
        from langsmith import Client

        Client().info  # property access; lightweight GET
        _connectivity_state = "ok"
        _connectivity_detail = None
    except Exception as exc:  # noqa: BLE001 — boundary
        # Sanitise: some langsmith error messages embed the host but
        # never the key. Still, strip anything that *could* be a token.
        msg = _redact(str(exc))
        logger.warning(
            "LangSmith reachability probe failed (%s: %s) — tracing remains "
            "enabled but spans may not be delivered",
            type(exc).__name__,
            msg,
        )
        _connectivity_state = "error"
        _connectivity_detail = f"{type(exc).__name__}: {msg}"[:200]

    logger.info(
        "LangSmith tracing: enabled  project=%s  tags=%s  connectivity=%s",
        lc_settings.project,
        ",".join(lc_settings.default_tags),
        _connectivity_state,
    )
    return True


def connectivity_status() -> tuple[str, str | None]:
    """Return ``(state, detail)`` from the startup reachability probe.

    ``state`` ∈ {"unknown", "ok", "error"}. The admin /system endpoint
    surfaces this so operators can tell "configured but unreachable"
    from "configured and streaming". Detail never carries secrets.
    """
    return _connectivity_state, _connectivity_detail


def _redact(text: str) -> str:
    """Strip anything that looks like a LangSmith API key from ``text``.

    LangSmith keys start with ``ls__`` or ``lsv2_`` followed by 40+ url-
    safe chars. We replace them with ``<redacted>`` so an unsanitised
    upstream error message can't leak the secret into logs or the admin
    response. This is defence-in-depth — the probe code paths above
    don't include the key in their exception strings — but cheap.
    """
    import re

    return re.sub(
        r"(ls(?:__|v2_)[A-Za-z0-9_\-]{20,})", "<redacted>", text
    )


# ── Callbacks ─────────────────────────────────────────────────────────────────

def get_callbacks() -> list["BaseCallbackHandler"]:
    """Callbacks to attach to LangChain runnables.

    Returns an empty list when tracing is disabled — passing this into a
    runnable is then a no-op (LangChain skips its tracing pipeline when
    no handlers are present and the env flag is off).
    """
    if not is_tracing_enabled():
        return []
    try:
        from langchain_core.tracers.langchain import LangChainTracer

        return [LangChainTracer(project_name=lc_settings.project)]
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.warning(
            "Failed to build LangSmith callback (%s: %s) — continuing untraced",
            type(exc).__name__,
            exc,
        )
        return []


def run_metadata(
    *,
    session_id: str | None = None,
    route: str | None = None,
    intent: str | None = None,
    confidence: float | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Common metadata block for a single query trace.

    Keys are kept stable so LangSmith filters/dashboards can be built
    against them: ``session_id``, ``route``, ``intent``, ``confidence``.
    """
    meta: dict[str, Any] = {}
    if session_id:
        meta["session_id"] = session_id
    if route:
        meta["route"] = route
    if intent:
        meta["intent"] = intent
    if confidence is not None:
        meta["confidence"] = round(float(confidence), 4)
    if extras:
        meta.update(extras)
    return meta


# ── Custom spans (for non-LangChain stages) ───────────────────────────────────

@asynccontextmanager
async def trace_span(
    name: str,
    *,
    run_type: str = "chain",
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
):
    """Record one span around a non-LangChain code block.

    Use for stages that don't already run through a LangChain runnable —
    e.g. the deterministic routing decision, the rerank pass, citation
    validation. When tracing is disabled, this is a cheap pass-through.

    Yields a dict the caller can mutate to attach outputs/metrics:
    ``span['outputs'] = {...}``, ``span['error'] = exc``. The dict is
    flushed to LangSmith on exit.
    """
    span: dict[str, Any] = {
        "name": name,
        "run_type": run_type,
        "inputs": {},
        "outputs": {},
        "metadata": dict(metadata or {}),
        "tags": list(tags or []) + list(lc_settings.default_tags),
    }

    if not is_tracing_enabled():
        yield span
        return

    started = time.perf_counter()
    client = None
    run_id: str | None = None
    try:
        from langsmith import Client

        client = Client()
        run = client.create_run(
            name=name,
            run_type=run_type,
            inputs=span["inputs"] or {"_": None},
            project_name=lc_settings.project,
            tags=span["tags"],
            extra={"metadata": span["metadata"]},
        )
        # langsmith.create_run returns either an id-bearing object or
        # None on some client versions — be defensive.
        run_id = getattr(run, "id", None) if run is not None else None
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.debug("trace_span(%s): create_run failed (%s)", name, exc)
        yield span
        return

    error: BaseException | None = None
    try:
        yield span
    except BaseException as exc:
        error = exc
        span["error"] = repr(exc)
        raise
    finally:
        if client is not None and run_id is not None:
            try:
                client.update_run(
                    run_id,
                    outputs=span["outputs"] or None,
                    error=repr(error) if error else None,
                    end_time=None,  # client fills with now
                    extra={
                        "metadata": {
                            **span["metadata"],
                            "elapsed_ms": round(
                                (time.perf_counter() - started) * 1000, 2
                            ),
                        }
                    },
                )
            except Exception as exc:  # noqa: BLE001 — boundary
                logger.debug("trace_span(%s): update_run failed (%s)", name, exc)
