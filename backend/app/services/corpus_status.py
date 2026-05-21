"""Live corpus-awareness helper.

Single source of truth for "what acts can LawFlow actually answer about
right now". Everything that needs to surface capability — the greeting
prose, the no-provision fallback, the System Health page, the
benchmark validator — calls into here so the answer is derived from
the running Chroma index, never from a hand-edited list.

Two distinct sets matter:

- **Supported** — acts declared in :data:`app.services.act_registry.ACT_REGISTRY`.
  The platform knows the alias, the domain, the topic mapping; the
  registry is the deployment-time contract.
- **Indexed** — acts whose chunks are actually present in the active
  Chroma collection (via ``vector_store.get_act_keys()``). This is the
  runtime truth.

Drift between the two means trouble: either an act was registered but
ingestion failed, or chunks live for an act that's no longer in the
registry. The :class:`CorpusStatus` snapshot makes that drift visible.

The lookup is intentionally cheap (single Chroma ``get`` for
metadatas) and is *not* cached at module level — callers cache via
``functools.lru_cache`` or the FastAPI dep system when they need
repeat reads, so a re-ingest is reflected immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.rag.vector_store import VectorStore, vector_store
from app.services.act_registry import ACT_REGISTRY


@dataclass
class CorpusActStatus:
    """Per-act readiness snapshot."""

    act_key: str
    name: str          # display name, e.g. "Indian Penal Code, 1860"
    indexed: bool
    chunk_count: int   # 0 when not indexed
    domain: str | None = None


@dataclass
class CorpusStatus:
    """Aggregate corpus-readiness snapshot used by every capability surface."""

    supported_keys: list[str] = field(default_factory=list)
    indexed_keys: list[str] = field(default_factory=list)
    missing_keys: list[str] = field(default_factory=list)
    orphan_keys: list[str] = field(default_factory=list)
    acts: list[CorpusActStatus] = field(default_factory=list)
    total_indexed_chunks: int = 0

    # ── Capability-prose helpers ─────────────────────────────────────────

    def display_names(self, *, indexed_only: bool = True) -> list[str]:
        """Sorted display names for the capability list shown to users.

        ``indexed_only=True`` (default) returns only acts the corpus
        can currently answer about — what we'd put in "available legal
        sources". ``False`` returns every supported act regardless of
        index state, useful for the admin readiness view.
        """
        rows = [
            a for a in self.acts
            if (a.indexed or not indexed_only)
        ]
        return sorted(a.name for a in rows)

    def short_labels(self, *, indexed_only: bool = True) -> list[str]:
        """Operator-friendly short tokens (e.g. 'IPC', 'BNS', 'CrPC').

        Falls back to the registry key when no convenient short token
        exists. Used by the conversational greeting where the full
        names would be unwieldy.
        """
        from app.services.act_registry import ACT_REGISTRY as _REG

        out: list[str] = []
        for a in self.acts:
            if indexed_only and not a.indexed:
                continue
            spec = _REG.get(a.act_key)
            # Prefer the short title if present in the spec's aliases,
            # else the canonical uppercase token (matches the IPC/BNS
            # convention), else the registry key.
            if spec is None:
                out.append(a.act_key.upper())
                continue
            short = (
                # First alias is usually the short token
                spec.aliases[0]
                if spec.aliases
                else None
            )
            if short and len(short) <= 12:
                out.append(short.upper() if short.isalpha() else short.title())
            else:
                out.append(spec.name)
        return sorted(set(out))


async def get_corpus_status(
    store: VectorStore = vector_store,
) -> CorpusStatus:
    """Build a fresh :class:`CorpusStatus` snapshot from the live Chroma store.

    Two reads:

    1. :func:`vector_store.get_act_keys` — the set of ``extra.act_key``
       values present in the active collection.
    2. ``vector_store.list_sources_summary`` — per-source chunk counts.

    The function does NOT hit the embedding model or the LLM; it's
    cheap enough to call on every request that needs a capability
    string. Memoise at the caller if you need many lookups inside one
    request.
    """
    from app.services.act_registry import ACT_DOMAINS

    indexed_keys = await store.get_act_keys()
    sources_summary = await store.list_sources_summary()

    # Per-act chunk-count rollup. The source string follows the
    # convention "{Act name} — Section/Article {N}: {Title}", so we
    # bucket by the matching act_key found via direct alias lookup.
    chunk_counts: dict[str, int] = dict.fromkeys(indexed_keys, 0)
    for row in sources_summary:
        meta_keys = {
            k for k, spec in ACT_REGISTRY.items()
            if str(row.get("source", "")).startswith(spec.name)
        }
        for k in meta_keys:
            chunk_counts[k] = chunk_counts.get(k, 0) + int(
                row.get("chunks_active", 0) or 0
            )

    acts: list[CorpusActStatus] = []
    for key, spec in ACT_REGISTRY.items():
        acts.append(
            CorpusActStatus(
                act_key=key,
                name=spec.name,
                indexed=key in indexed_keys,
                chunk_count=chunk_counts.get(key, 0),
                domain=ACT_DOMAINS.get(key),
            )
        )
    # Stable ordering — alphabetical by display name keeps the JSON
    # diffable across runs and the UI table stably sorted.
    acts.sort(key=lambda a: a.name)

    supported = sorted(ACT_REGISTRY.keys())
    indexed = sorted(indexed_keys & set(supported))
    missing = sorted(set(supported) - indexed_keys)
    orphan = sorted(indexed_keys - set(supported))

    return CorpusStatus(
        supported_keys=supported,
        indexed_keys=indexed,
        missing_keys=missing,
        orphan_keys=orphan,
        acts=acts,
        total_indexed_chunks=sum(a.chunk_count for a in acts if a.indexed),
    )


# ── Synchronous variant for the conversational scaffolding ─────────────────
#
# The greeting / clarification helpers in :mod:`app.services.legal_service`
# run inside the request-processing critical path and read capability
# information *while* the async event loop is mid-orchestration. Doing
# another ``await`` there would serialise more than necessary — we
# offer a sync best-effort flavour that reads the registry only.
# Result: "the platform supports X, Y, Z" — accurate against the
# deployment contract, even if a particular act hasn't ingested. The
# more honest "what's actually indexed right now" answer is reserved
# for the async path consumed by the admin endpoint + the no-provision
# overview fallback.


def _short_titles() -> dict[str, str]:
    """Lazy, cached short-title lookup keyed by act_key.

    Reads ``short_title`` straight out of each act's JSON file. The
    canonical casing lives in the corpus ("IPC", "CrPC", "MV Act") and
    we want to preserve it verbatim — building short tokens from the
    alias strings ends up mangling case ("Mv Act", "It Act").
    """
    import json
    from pathlib import Path

    cached = getattr(_short_titles, "_cache", None)
    if cached is not None:
        return cached

    acts_dir = (
        Path(__file__).resolve().parent.parent / "data" / "acts"
    )
    out: dict[str, str] = {}
    for key, spec in ACT_REGISTRY.items():
        path = acts_dir / spec.filename
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — boundary: missing file shouldn't crash
            continue
        title = data.get("short_title")
        if title:
            out[key] = str(title)
    _short_titles._cache = out  # type: ignore[attr-defined]
    return out


def supported_acts_brief() -> list[str]:
    """Sync helper — short, user-friendly labels of every registered act.

    Pulls each act's ``short_title`` directly from its JSON file. That
    string is the canonical casing the corpus team curated (``IPC``,
    ``CrPC``, ``MV Act``) — much friendlier than the long display name
    and faithful to Indian legal shorthand. Falls back to the registry
    name when an act doesn't carry a short_title.

    Ordering: the high-traffic "common law" core comes first (IPC, BNS,
    CrPC, BNSS, Constitution, Evidence Act), then everything else
    alphabetical. This keeps the user-facing capability prose readable
    even when truncated — the most-asked-about acts always appear in
    the visible head.
    """
    titles = _short_titles()
    _HEAD_ORDER = (
        "ipc",
        "bns",
        "crpc",
        "bnss",
        "constitution",
        "evidence",
    )
    head: list[str] = []
    seen: set[str] = set()
    for key in _HEAD_ORDER:
        spec = ACT_REGISTRY.get(key)
        if spec is None:
            continue
        label = titles.get(key) or spec.name
        if label not in seen:
            seen.add(label)
            head.append(label)
    tail: list[str] = []
    for key, spec in ACT_REGISTRY.items():
        if key in _HEAD_ORDER:
            continue
        label = titles.get(key) or spec.name
        if label not in seen:
            seen.add(label)
            tail.append(label)
    return head + sorted(tail)


def supported_acts_long() -> list[str]:
    """Sync helper — full display names of every registered act.

    Same source as ``supported_acts_brief`` but unabbreviated. Used by
    the System Health surface where the full name is the right level
    of detail.
    """
    return sorted(spec.name for spec in ACT_REGISTRY.values())


__all__ = [
    "CorpusActStatus",
    "CorpusStatus",
    "get_corpus_status",
    "supported_acts_brief",
    "supported_acts_long",
]
