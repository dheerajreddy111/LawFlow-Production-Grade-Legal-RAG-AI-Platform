"""
Lightweight in-process conversational memory for LawFlow.

Keeps a bounded, per-session window of recent turns so the orchestrator can
resolve follow-ups ("What is IPC 420?" → "What is the punishment?" infers
"punishment for Section 420 IPC"). Deliberately simple: a dict of deques,
process-local, no external store — enough for a single-process deployment
and trivially swappable for Redis later behind the same API.

The memory only *augments* the query string before classification; it never
changes the response schema or the routing/RAG architecture.
"""

from __future__ import annotations

import os
import re
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from app.services.act_registry import topic_acts

# Configurable window (number of turns retained per session).
MEMORY_WINDOW: int = int(os.getenv("MEMORY_WINDOW", "6"))
# Hard cap on concurrent sessions retained. Without this the session dict
# grows unbounded (one entry per browser tab, never evicted) → slow memory
# leak / unbounded-growth vector. LRU-evict the least-recently-used session.
MEMORY_MAX_SESSIONS: int = int(os.getenv("MEMORY_MAX_SESSIONS", "500"))

_SELF_CONTAINED = re.compile(
    r"\b(section|sec\.?|article|art\.?|ipc|crpc|cpc|bns|bnss|"
    r"\bact\b|constitution)\b",
    re.I,
)
# Short, subjectless phrasings that lean on the previous turn.
_FOLLOWUP_CUE = re.compile(
    r"^\s*(what|and|its|it|how|when|where|why|is|are|can|does|do|"
    r"any|give|list|show|more|also|elaborate|continue|"
    r"explain|tell\s+me|what\s+about|punishment|penalty|exceptions?|"
    r"defen[cs]e|procedure|meaning|example|that|this|the\s+punishment)\b",
    re.I,
)


@dataclass
class Turn:
    query: str
    intent: str
    route: str
    subject: str = ""          # e.g. "Section 420 IPC" — the legal anchor
    domain: str = ""
    entities: list[dict] = field(default_factory=list)


class ConversationMemory:
    """Thread-safe, bounded per-session turn history."""

    def __init__(
        self,
        window: int = MEMORY_WINDOW,
        max_sessions: int = MEMORY_MAX_SESSIONS,
    ) -> None:
        self._window = window
        self._max_sessions = max_sessions
        # OrderedDict as an LRU: most-recently-touched session at the end.
        self._store: OrderedDict[str, deque[Turn]] = OrderedDict()
        self._lock = threading.Lock()

    def record(self, session_id: str | None, turn: Turn) -> None:
        if not session_id:
            return
        with self._lock:
            dq = self._store.get(session_id)
            if dq is None:
                dq = deque(maxlen=self._window)
            self._store[session_id] = dq
            self._store.move_to_end(session_id)
            dq.append(turn)
            # Evict least-recently-used sessions beyond the cap.
            while len(self._store) > self._max_sessions:
                self._store.popitem(last=False)

    def recent(self, session_id: str | None) -> list[Turn]:
        if not session_id:
            return []
        with self._lock:
            dq = self._store.get(session_id)
            if dq is None:
                return []
            self._store.move_to_end(session_id)  # touch = keep alive
            return list(dq)

    def last_subject(self, session_id: str | None) -> str:
        """Most recent legal anchor (section/act) from prior turns."""
        for turn in reversed(self.recent(session_id)):
            if turn.subject:
                return turn.subject
        return ""

    @staticmethod
    def is_followup(query: str) -> bool:
        """True only when the query is short, subjectless, and leans on the
        previous turn.

        A query is NOT a follow-up if it carries its own legal subject —
        either an explicit statute/section token (_SELF_CONTAINED) or a
        recognised legal *topic* (e.g. "what is bail?", "is fraud a crime?").
        Binding such self-contained questions to a stale subject pollutes
        context and wrecks retrieval precision. Reuses the act-registry's
        topic intelligence rather than duplicating a keyword list.
        """
        if _SELF_CONTAINED.search(query):
            return False
        if topic_acts(query):
            return False  # names its own legal topic → self-contained
        words = query.split()
        return len(words) <= 7 and bool(_FOLLOWUP_CUE.match(query))

    def resolve(self, session_id: str | None, query: str) -> tuple[str, str]:
        """Return (effective_query, note).

        If *query* is a follow-up and prior legal context exists, append the
        remembered subject so classification/retrieval resolve it correctly.
        The original query is still what the user sees; only the effective
        query drives routing.
        """
        if not session_id:
            return query, ""
        if not self.is_followup(query):
            return query, ""
        subject = self.last_subject(session_id)
        if not subject:
            return query, ""
        return f"{query} regarding {subject}", f"follow-up resolved to “{subject}”"

    def stats(self) -> dict[str, int]:
        """Thread-safe snapshot of memory occupancy for the admin dashboard.

        ``sessions``     active session ids in the LRU store
        ``turns_total``  total turns retained across all sessions
        ``max_sessions`` configured LRU cap
        ``window``       per-session turn cap
        """
        with self._lock:
            sessions = len(self._store)
            turns_total = sum(len(dq) for dq in self._store.values())
        return {
            "sessions": sessions,
            "turns_total": turns_total,
            "max_sessions": self._max_sessions,
            "window": self._window,
        }


# Module-level singleton — shared across requests.
conversation_memory = ConversationMemory()


def build_subject(entities: list[dict]) -> str:
    """Compose a stable legal anchor from extracted entities.

    'Section 420' + 'IPC' → 'Section 420 IPC'.
    """
    sec = next(
        (e["value"] for e in entities if e.get("type") in ("SECTION", "ARTICLE")),
        "",
    )
    act = next(
        (e["value"] for e in entities if e.get("type") == "ACT"),
        "",
    )
    if sec and act:
        return f"{sec} {act}"
    return sec or act
