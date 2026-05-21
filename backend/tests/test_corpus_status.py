"""Live corpus-awareness regressions.

Three properties keep the assistant honest about what it can answer:

  - The capability prose the user sees comes from
    :mod:`app.services.corpus_status`, never from a hand-edited list.
  - Greeting / clarify / no-provision fallbacks pull the latest acts
    every time, so adding or removing a registered act updates the
    message without code changes.
  - The corpus-status snapshot exposes the supported vs indexed split
    so the System Health page can flag drift.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.corpus_status import (
    supported_acts_brief,
    supported_acts_long,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Synchronous helpers (sourced from ACT_REGISTRY) ────────────────────────


def test_supported_acts_brief_uses_canonical_short_titles() -> None:
    """Short labels read the ``short_title`` field from each act JSON,
    not a guessed casing of the alias. ``IPC`` / ``CrPC`` / ``MV Act``
    are the legal-shorthand conventions the corpus team curated."""
    names = supported_acts_brief()
    assert "IPC" in names
    assert "CrPC" in names
    assert "MV Act" in names
    assert "IT Act" in names
    assert "NI Act" in names
    assert "BNSS" in names
    assert "PWDVA" in names
    # No malformed casings.
    assert "Mv Act" not in names
    assert "It Act" not in names


def test_supported_acts_brief_starts_with_common_law_core() -> None:
    """The head of the list is curated (IPC / BNS / CrPC / BNSS /
    Constitution / Evidence Act) so the most-asked-about acts always
    appear in the visible head of any truncated capability message."""
    names = supported_acts_brief()
    assert names[:6] == [
        "IPC",
        "BNS",
        "CrPC",
        "BNSS",
        "Constitution",
        "Evidence Act",
    ]
    # The tail after the head is alphabetical for stable diffs.
    tail = names[6:]
    assert tail == sorted(tail)


def test_supported_acts_brief_matches_registry_size() -> None:
    """One short label per registered act — no dupes, no missing."""
    from app.services.act_registry import ACT_REGISTRY

    assert len(supported_acts_brief()) == len(ACT_REGISTRY)


def test_supported_acts_long_returns_full_names() -> None:
    """Long form returns formal display names ('Indian Penal Code,
    1860') — useful for the System Health table where short tokens
    would be ambiguous."""
    names = supported_acts_long()
    assert "Indian Penal Code, 1860" in names
    assert "Motor Vehicles Act, 1988" in names
    assert "Constitution of India, 1950" in names


# ── Async corpus-status snapshot ───────────────────────────────────────────


def test_get_corpus_status_lists_supported_indexed_missing() -> None:
    """Snapshot exposes the three sets used by the System Health card."""
    from app.rag.ingest import ingest_corpora
    from app.services.corpus_status import get_corpus_status

    async def go() -> None:
        await ingest_corpora()
        snap = await get_corpus_status()
        assert isinstance(snap.supported_keys, list)
        assert isinstance(snap.indexed_keys, list)
        assert isinstance(snap.missing_keys, list)
        assert isinstance(snap.orphan_keys, list)
        # Under normal operation the deployment contract holds.
        assert not snap.orphan_keys, (
            f"orphan acts present: {snap.orphan_keys}"
        )
        assert snap.total_indexed_chunks > 0
        # Per-act readiness rows exist and the boolean flags match.
        for row in snap.acts:
            assert (row.act_key in snap.indexed_keys) == row.indexed
            if row.indexed:
                assert row.chunk_count > 0

    _run(go())


# ── Greeting / clarify use the live list ───────────────────────────────────


def test_greeting_mentions_a_supported_act() -> None:
    """`_greeting()` splices the live act list — if a new act is added
    to the registry it should appear here automatically (no code edit
    needed)."""
    from app.services.legal_service import _greeting

    text = _greeting()
    # At least one canonical short token from the corpus should appear.
    short_titles = supported_acts_brief()
    assert any(s in text for s in short_titles), (
        "Greeting should list at least one indexed act"
    )
    # Capability count is mentioned.
    assert str(len(short_titles)) in text


def test_clarify_does_not_list_acts_inline() -> None:
    """Clarify text uses domain examples, not a frozen act list.

    The goal is to nudge the user toward a question shape; a long
    list of acts would distract. The greeting + System Health surface
    the full capability inventory.
    """
    from app.services.legal_service import _clarify

    text = _clarify()
    # No hardcoded "IPC, BNS, CrPC, BNSS, ..." style enumeration.
    assert "IPC, BNS" not in text


# ── No-provision overview fallback ─────────────────────────────────────────


def test_overview_no_act_resolved_message_is_runtime_derived() -> None:
    """When overview asks for an Act we can't identify, the message
    lists what we DO carry — derived from the registry, not a frozen
    string."""
    from app.routing.engine import Route
    from app.services.legal_service import _compose_answer

    out = _compose_answer(Route.RAG, [], "no act resolved", overview_mode=True)
    # Some recognisable short titles must appear — they come from
    # ``supported_acts_brief`` so this proves the list is live.
    assert "IPC" in out
    assert "MV Act" in out
    # Disclaimer wording from the runtime helper.
    assert "Available legal sources right now" in out


# ── Benchmark validator end-to-end ─────────────────────────────────────────


def test_benchmark_validator_finds_no_missing_acts() -> None:
    """The shipped benchmark CSV must only target indexed acts.

    This is the regression that catches a corpus shrinkage breaking
    the evaluation harness silently.
    """
    import subprocess
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    venv_py = backend / ".venv" / "bin" / "python"
    if not venv_py.exists():
        pytest.skip("venv python not available in this environment")

    result = subprocess.run(
        [str(venv_py), str(backend / "scripts" / "validate_benchmark.py")],
        cwd=str(backend),
        capture_output=True,
        text=True,
        timeout=120,
    )
    # Exit 0 = no missing acts; 1 = missing; 2 = bad invocation.
    assert result.returncode == 0, (
        f"validator failed:\n--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
