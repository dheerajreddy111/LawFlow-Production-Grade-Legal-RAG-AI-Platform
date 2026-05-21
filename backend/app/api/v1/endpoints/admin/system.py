"""GET /api/v1/admin/system — vector store + LangSmith + LLM providers
+ memory + process snapshot.

Secrets policy: API keys are never serialised. Only presence flags +
the public model identifier (e.g. ``llama-3.3-70b-versatile``) appear.
"""

from __future__ import annotations

import sys
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import User, require_admin
from app.rag.vector_store import vector_store
from app.services.metrics import metrics

router = APIRouter()


# ── Response shapes ─────────────────────────────────────────────────────────


class VectorStoreStatus(BaseModel):
    collection: str
    count: int
    embedding_dim: int
    path: str


class LangSmithStatus(BaseModel):
    """Operator-facing view of LangSmith tracing health.

    ``configured`` keeps its existing contract (flag on AND key set);
    the broken-out fields below let the System Health page diagnose
    "enabled but no key" or "configured but the probe failed".
    Connectivity reflects a startup-time reachability check; we don't
    re-probe on every /system call. The API key itself is NEVER
    serialised — only its presence/absence flag.
    """

    configured: bool
    project: str
    endpoint: str | None = None
    # Separate flag + key visibility so the UI can distinguish "tracing
    # flag is on but no key was supplied" from "everything wired".
    tracing_flag_enabled: bool = False
    api_key_present: bool = False
    # Startup reachability probe outcome.
    # One of "unknown" | "ok" | "error".
    connectivity: str = "unknown"
    # Short, secret-free description of the last probe error, if any.
    connectivity_detail: str | None = None


class LLMProviderInfo(BaseModel):
    name: str  # "groq" | "anthropic" | "openai"
    configured: bool
    model: str | None = None


class LLMProvidersStatus(BaseModel):
    active: str | None  # the provider currently used by RAG (best-effort)
    providers: list[LLMProviderInfo]


class MemoryStatus(BaseModel):
    sessions: int
    turns_total: int
    max_sessions: int
    window: int


class ProcessStatus(BaseModel):
    environment: str
    debug: bool
    python_version: str
    uptime_seconds: float


class HealthCheck(BaseModel):
    """One named subsystem check (renders as a row in the UI's status banner)."""

    name: str
    ok: bool
    detail: str


class CounterEntry(BaseModel):
    name: str
    value: int


class CorpusActRow(BaseModel):
    """Per-act readiness row surfaced on the System Health page."""

    act_key: str
    name: str
    indexed: bool
    chunk_count: int
    domain: str | None = None


class CorpusStatusBlock(BaseModel):
    """Live corpus readiness — registered vs indexed acts.

    Surfaces drift between the registry (deployment contract) and the
    on-disk Chroma index. ``missing_keys`` and ``orphan_keys`` should be
    empty under normal operation; non-empty values flag an operator
    that re-ingestion is needed.
    """

    supported_keys: list[str]
    indexed_keys: list[str]
    missing_keys: list[str]
    orphan_keys: list[str]
    total_indexed_chunks: int
    acts: list[CorpusActRow]


class SystemResponse(BaseModel):
    status: str  # "ok" | "degraded"
    checks: list[HealthCheck]
    vector_store: VectorStoreStatus
    langsmith: LangSmithStatus
    llm_providers: LLMProvidersStatus
    memory: MemoryStatus
    process: ProcessStatus
    ingest_failures: list[CounterEntry]
    error_counters: list[CounterEntry]
    corpus: CorpusStatusBlock


# ── Builders ────────────────────────────────────────────────────────────────


def _llm_providers_status() -> LLMProvidersStatus:
    """Best-effort view of which LLM providers are configured.

    'active' follows the same precedence the RAG engine uses: prefer
    Groq when its key is set (cheap + fast), then Anthropic, then
    OpenAI. Keys are never serialised — only presence.
    """
    from app.config import settings as app_settings

    groq_on = bool(app_settings.groq_api_key)
    anth_on = bool(app_settings.anthropic_api_key)
    openai_on = bool(app_settings.openai_api_key)

    providers = [
        LLMProviderInfo(
            name="groq",
            configured=groq_on,
            model=app_settings.groq_model if groq_on else None,
        ),
        LLMProviderInfo(name="anthropic", configured=anth_on),
        LLMProviderInfo(name="openai", configured=openai_on),
    ]
    active: str | None = None
    if groq_on:
        active = "groq"
    elif anth_on:
        active = "anthropic"
    elif openai_on:
        active = "openai"
    return LLMProvidersStatus(active=active, providers=providers)


def _filter_counters(snap: dict, prefix: str) -> list[CounterEntry]:
    counters = snap.get("counters") or {}
    rows: list[CounterEntry] = []
    for name, val in counters.items():
        if name.startswith(prefix):
            rows.append(CounterEntry(name=name, value=int(val)))
    rows.sort(key=lambda c: c.value, reverse=True)
    return rows


def _langsmith_detail(ls: LangSmithStatus) -> str:
    """Render the operator-facing one-liner for the LangSmith check.

    Spelling out the four states ("off" / "flag only" / "key only" /
    "configured + ${connectivity}") is more useful than a generic
    "enabled / disabled" label — operators looking at the System Health
    banner can act without opening LangSmith.
    """
    if not ls.tracing_flag_enabled and not ls.api_key_present:
        return "disabled (set LANGCHAIN_TRACING_V2 + LANGCHAIN_API_KEY)"
    if ls.tracing_flag_enabled and not ls.api_key_present:
        return "flag on but LANGCHAIN_API_KEY missing — tracing inactive"
    if not ls.tracing_flag_enabled and ls.api_key_present:
        return "key present but LANGCHAIN_TRACING_V2=false — tracing inactive"
    base = f"enabled · project {ls.project}"
    if ls.connectivity == "ok":
        return f"{base} · reachable"
    if ls.connectivity == "error":
        return f"{base} · UNREACHABLE ({ls.connectivity_detail or 'probe failed'})"
    return f"{base} · reachability unknown"


def _derive_checks(
    vs: VectorStoreStatus,
    llm: LLMProvidersStatus,
    ls: LangSmithStatus,
    corpus: "CorpusStatusBlock",
) -> tuple[str, list[HealthCheck]]:
    """Reduce subsystem status into a banner-level ok/degraded label."""
    checks = [
        HealthCheck(
            name="Vector store",
            ok=vs.count > 0,
            detail=f"{vs.count:,} chunks in {vs.collection}",
        ),
        HealthCheck(
            name="LLM provider",
            ok=llm.active is not None,
            detail=(
                f"active: {llm.active}"
                if llm.active
                else "no provider key configured (RAG path will fail)"
            ),
        ),
        HealthCheck(
            name="LangSmith tracing",
            # Configured-but-unreachable is the only state worth flagging
            # as degraded; "off" is a legitimate production posture and
            # "on + ok" or "on + unknown probe" should both look green.
            ok=not (ls.configured and ls.connectivity == "error"),
            detail=_langsmith_detail(ls),
        ),
        # Corpus parity — non-empty missing/orphan flags operator drift
        # between ACT_REGISTRY and the on-disk Chroma index.
        HealthCheck(
            name="Corpus parity",
            ok=not corpus.missing_keys and not corpus.orphan_keys,
            detail=(
                f"{len(corpus.indexed_keys)}/{len(corpus.supported_keys)} "
                "acts indexed"
                + (
                    f" · missing: {', '.join(corpus.missing_keys)}"
                    if corpus.missing_keys
                    else ""
                )
                + (
                    f" · orphan: {', '.join(corpus.orphan_keys)}"
                    if corpus.orphan_keys
                    else ""
                )
            ),
        ),
    ]
    overall = "ok" if all(c.ok for c in checks) else "degraded"
    return overall, checks


# ── Route ───────────────────────────────────────────────────────────────────


@router.get(
    "/system",
    response_model=SystemResponse,
    summary="System health snapshot for the admin dashboard",
)
async def system_health(
    _admin: Annotated[User, Depends(require_admin)],
) -> SystemResponse:
    from app.config import settings as app_settings
    from app.integrations.lc import connectivity_status
    from app.integrations.lc.settings import lc_settings
    from app.services.memory import conversation_memory

    vs_raw = await vector_store.collection_stats()
    vs = VectorStoreStatus(
        collection=str(vs_raw.get("collection", "")),
        count=int(vs_raw.get("count", 0)),
        embedding_dim=int(vs_raw.get("embedding_dim", 0)),
        path=str(vs_raw.get("path", "")),
    )
    conn_state, conn_detail = connectivity_status()
    ls = LangSmithStatus(
        configured=bool(lc_settings.tracing_enabled and lc_settings.api_key),
        project=lc_settings.project,
        endpoint=lc_settings.endpoint,
        tracing_flag_enabled=bool(lc_settings.tracing_enabled),
        api_key_present=bool(lc_settings.api_key),
        connectivity=conn_state,
        connectivity_detail=conn_detail,
    )
    llm = _llm_providers_status()

    mem_raw = conversation_memory.stats()
    memory = MemoryStatus(
        sessions=mem_raw["sessions"],
        turns_total=mem_raw["turns_total"],
        max_sessions=mem_raw["max_sessions"],
        window=mem_raw["window"],
    )

    snap = metrics.snapshot()
    process = ProcessStatus(
        environment=app_settings.environment,
        debug=app_settings.debug,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        uptime_seconds=float(snap.get("uptime_seconds", 0.0)),
    )

    # Live corpus readiness — registered vs indexed acts.
    from app.services.corpus_status import get_corpus_status

    snapshot = await get_corpus_status()
    corpus = CorpusStatusBlock(
        supported_keys=snapshot.supported_keys,
        indexed_keys=snapshot.indexed_keys,
        missing_keys=snapshot.missing_keys,
        orphan_keys=snapshot.orphan_keys,
        total_indexed_chunks=snapshot.total_indexed_chunks,
        acts=[
            CorpusActRow(
                act_key=a.act_key,
                name=a.name,
                indexed=a.indexed,
                chunk_count=a.chunk_count,
                domain=a.domain,
            )
            for a in snapshot.acts
        ],
    )

    overall, checks = _derive_checks(vs, llm, ls, corpus)
    return SystemResponse(
        status=overall,
        checks=checks,
        vector_store=vs,
        langsmith=ls,
        llm_providers=llm,
        memory=memory,
        process=process,
        ingest_failures=_filter_counters(snap, "ingest_failures"),
        error_counters=_filter_counters(snap, "errors"),
        corpus=corpus,
    )
