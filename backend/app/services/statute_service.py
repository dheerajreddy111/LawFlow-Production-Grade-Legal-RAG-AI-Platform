"""
StatuteService — deterministic statute/article retrieval over a multi-domain
in-memory corpus (IPC, BNS, CrPC, BNSS, Constitution, Evidence Act, MV Act,
Consumer Protection Act, IT Act).

Given a list of extracted LegalEntity objects (and, optionally, the raw
query), the service:
    1. Resolves any ACT entity to a canonical corpus via ACT_ALIASES.
    2. Looks up SECTION / ARTICLE entities — scoped to the resolved act when
       one is named, otherwise across every corpus (cross-act retrieval).
    3. Falls back to the base number when a sub-clause is not indexed
       ("Section 138A(1)" → "138A(1)" → "138A").
    4. As a last resort, expands the query through TOPIC_SYNONYMS and does a
       cross-act keyword search so topical questions still surface law.

All corpora are loaded once at construction from ACT_REGISTRY; no I/O per
request. The public API — `retrieve(entities)` returning
`StatuteRetrievalResult[SectionResult]` — is unchanged; the optional
`query=` argument is additive and backward compatible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

from pydantic import BaseModel, Field

from app.entities.extractor import EntityType, LegalEntity
from app.services.act_registry import (
    ACT_REGISTRY,
    expand_topics,
    resolve_act,
    topic_acts,
)

# ── Data paths ────────────────────────────────────────────────────────────────

_ACTS_DIR: Final[Path] = (
    Path(__file__).resolve().parent.parent / "data" / "acts"
)

_PREFIX = re.compile(r"^(?:section|sec\.?|article|art\.?)\s*", re.I)
_SUB_CLAUSE = re.compile(r"\s*\([^)]+\)$")

_TOPIC_RESULT_LIMIT: Final[int] = 5


# ── Public types ──────────────────────────────────────────────────────────────

class SectionResult(BaseModel):
    number:    str
    title:     str
    content:   str
    citations: list[str]
    # Additive, optional → preserves the existing response contract.
    act:       str | None = None
    unit:      str = "section"   # "section" | "article"
    keywords:  list[str] = Field(default_factory=list)


class StatuteRetrievalResult(BaseModel):
    sections:           list[SectionResult]
    matched_entities:   list[str]
    unmatched_entities: list[str]


# ── Internal corpus container ─────────────────────────────────────────────────

class _Corpus:
    """One act: number→SectionResult index, plus its act-key."""

    __slots__ = ("act_key", "by_number")

    def __init__(self, act_key: str) -> None:
        self.act_key = act_key
        self.by_number: dict[str, SectionResult] = {}


# ── Service ───────────────────────────────────────────────────────────────────

class StatuteService:
    """Stateless retrieval service — safe to share across async tasks."""

    def __init__(self) -> None:
        self._corpora: dict[str, _Corpus] = {}
        # keyword (lowercased) → [(act_key, SectionResult), ...]
        self._keyword_index: dict[str, list[tuple[str, SectionResult]]] = {}
        self._load()

    # ── public API ────────────────────────────────────────────────────────────

    async def retrieve(
        self,
        entities: list[LegalEntity],
        query: str | None = None,
        *,
        primary_only: bool = False,
    ) -> StatuteRetrievalResult:
        """Return corpus provisions matching the entities (and, as a topical
        fallback, the query). API-compatible: `query` is optional.

        ``primary_only`` (used by the deterministic route) returns just the
        single best exact match per section/article entity — the first by
        registry order — and disables cross-act duplication and the topical
        keyword fallback, so an explicit statute query never surfaces
        unrelated provisions. Default ``False`` preserves the cross-act +
        topical behaviour relied on by the RAG fallback path."""
        ref_entities = [
            e
            for e in entities
            if e.type in (EntityType.SECTION, EntityType.ARTICLE)
        ]
        act_keys = self._resolve_acts(entities)

        sections: list[SectionResult] = []
        matched: list[str] = []
        unmatched: list[str] = []
        seen: set[tuple[str | None, str]] = set()

        def add(sr: SectionResult) -> bool:
            key = (sr.act, sr.number)
            if key in seen:
                return False
            seen.add(key)
            sections.append(sr)
            return True

        for ent in ref_entities:
            number = _normalise(ent.value)
            scope = act_keys or list(self._corpora.keys())
            hit = False
            for ak in scope:
                sr = self._lookup_in(ak, number)
                if sr is not None:
                    add(sr)
                    hit = True
                    # Stop at the first (primary) match when an act is named
                    # OR when primary_only is set. Only the default cross-act
                    # mode keeps scanning sibling corpora.
                    if act_keys or primary_only:
                        break
            (matched if hit else unmatched).append(ent.value)

        # Topical cross-act fallback when no exact provision resolved.
        # Skipped under primary_only — explicit statute queries must not
        # broaden into keyword/semantic matches.
        if not sections and query and not primary_only:
            # Scope to the topic's relevant acts so a shared keyword doesn't
            # pull an unrelated provision from the wrong corpus.
            scoped = act_keys or topic_acts(query)
            for kw in expand_topics(query):
                for ak, sr in self._keyword_index.get(kw.lower(), []):
                    if scoped and ak not in scoped:
                        continue
                    add(sr)
                    if len(sections) >= _TOPIC_RESULT_LIMIT:
                        break
                if len(sections) >= _TOPIC_RESULT_LIMIT:
                    break

        return StatuteRetrievalResult(
            sections=sections,
            matched_entities=matched,
            unmatched_entities=unmatched,
        )

    # ── resolution helpers ────────────────────────────────────────────────────

    def _resolve_acts(self, entities: list[LegalEntity]) -> list[str]:
        keys: list[str] = []
        for e in entities:
            if e.type == EntityType.ACT:
                k = resolve_act(e.value)
                if k and k in self._corpora and k not in keys:
                    keys.append(k)
        return keys

    def _lookup_in(self, act_key: str, number: str) -> SectionResult | None:
        corpus = self._corpora.get(act_key)
        if corpus is None:
            return None
        if number in corpus.by_number:
            return corpus.by_number[number]
        base = _SUB_CLAUSE.sub("", number)
        return corpus.by_number.get(base) if base != number else None

    # ── loader ────────────────────────────────────────────────────────────────

    def _load(self) -> None:
        for spec in ACT_REGISTRY.values():
            path = _ACTS_DIR / spec.filename
            raw = json.loads(path.read_text(encoding="utf-8"))
            corpus = _Corpus(spec.key)
            for entry in raw.get("sections", []):
                section = SectionResult(
                    number=entry["number"],
                    title=entry["title"],
                    content=entry["content"],
                    citations=entry.get("citations", []),
                    act=spec.name,
                    unit=spec.unit,
                    keywords=entry.get("keywords", []),
                )
                corpus.by_number[section.number.upper()] = section
                for kw in section.keywords:
                    self._keyword_index.setdefault(kw.lower(), []).append(
                        (spec.key, section)
                    )
            self._corpora[spec.key] = corpus


def _normalise(entity_value: str) -> str:
    """'Section 25F' → '25F', 'Article 21' → '21', 'Sec. 302' → '302'."""
    stripped = _PREFIX.sub("", entity_value.strip())
    return stripped.upper()
