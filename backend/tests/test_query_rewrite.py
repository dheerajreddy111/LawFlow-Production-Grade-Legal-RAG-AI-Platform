"""Query rewriting + metadata-filter regressions."""

from __future__ import annotations

import pytest

from app.rag.query_rewrite import (
    build_metadata_filter,
    detect_act_keys,
    detect_section_numbers,
    rewrite_query,
)


def test_detect_act_keys_finds_direct_aliases():
    keys = detect_act_keys("Explain section 25F of the IPC")
    assert "ipc" in keys


def test_detect_act_keys_finds_topic_inferred():
    keys = detect_act_keys("Can I get bail?")
    # `bail` resolves to CrPC / BNSS via topic_acts.
    assert "crpc" in keys
    assert "bnss" in keys


def test_detect_section_numbers():
    assert "25f" in detect_section_numbers("Section 25F of the IDA")
    assert "21" in detect_section_numbers("Article 21")
    assert "185" in detect_section_numbers("§185 of the MV Act")


def test_rewrite_query_expands_synonyms():
    out = rewrite_query("Can I drink and drive?")
    # The expansion contains topic synonyms from the registry.
    low = out.expanded.lower()
    assert "drunk driving" in low or "under influence" in low
    # The original query is always the first variant.
    assert out.variants[0] == "Can I drink and drive?"
    # The expansion is also a variant.
    assert any("drunk" in v.lower() or "under" in v.lower() for v in out.variants)


def test_rewrite_query_anchors_section_variant():
    out = rewrite_query("What does section 25F of the IPC say?")
    # Has an act anchor variant.
    assert out.act_keys and out.sections
    assert any("section 25f" in v.lower() for v in out.variants)


def test_build_metadata_filter_single_act():
    f = build_metadata_filter(["ipc"])
    assert f == {"extra.act_key": "ipc"}


def test_build_metadata_filter_multi_act():
    f = build_metadata_filter(["ipc", "bns"])
    assert f and f.get("extra.act_key", {}).get("$in") == ["ipc", "bns"]


def test_build_metadata_filter_with_jurisdiction():
    f = build_metadata_filter(["ipc"], jurisdiction="India")
    assert f and "$and" in f
    clauses = f["$and"]
    assert {"extra.act_key": "ipc"} in clauses
    assert {"extra.jurisdiction": "India"} in clauses


def test_build_metadata_filter_empty_returns_none():
    """An empty filter must be None, not {} — Chroma rejects empty where."""
    assert build_metadata_filter([]) is None
