"""Tests for the admin dashboard endpoints.

Covers:
- /overview: auth gating, response shape, route_share math
- /documents: auth gating, list shape, detail with versions, delete
  happy path, delete-missing returns 404
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rag.chunker import ChunkConfig, DocumentChunker
from app.rag.vector_store import vector_store
from app.rag.versioning import ingest_versioned_text
from app.services.metrics import metrics
from tests.conftest import signup_admin, signup_user


def test_overview_requires_auth():
    with TestClient(app) as client:
        r = client.get("/api/v1/admin/overview")
        assert r.status_code == 401


def test_overview_requires_admin():
    with TestClient(app) as client:
        headers = signup_user(client, email="alice@example.com")
        r = client.get("/api/v1/admin/overview", headers=headers)
        assert r.status_code == 403


def test_overview_shape_and_users_count():
    """Admin can read the overview; user counts reflect the DB; section
    shape matches the OverviewResponse contract."""
    metrics.reset()
    with TestClient(app) as client:
        admin_headers = signup_admin(client, email="admin@example.com")
        # Sign up two more users to exercise the user counts.
        signup_user(client, email="u1@example.com")
        signup_user(client, email="u2@example.com")

        r = client.get("/api/v1/admin/overview", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()

        # Top-level sections present
        for key in ("documents", "queries", "latency", "ingestion", "users", "uptime_seconds"):
            assert key in body, f"missing section {key}"

        # Users: 1 admin + 2 plain users + 0 disabled
        assert body["users"]["total"] == 3
        assert body["users"]["active"] == 3
        assert body["users"]["admins"] == 1

        # Queries: no requests yet → zero counters
        assert body["queries"]["total"] == 0
        assert body["queries"]["by_route"] == {}
        assert body["queries"]["route_share"] == {}

        # Latency: histograms empty
        assert body["latency"]["count"] == 0


def test_overview_route_share_computes_percentages():
    """After a couple of /query calls, route_share equals counter / total."""
    metrics.reset()
    with TestClient(app) as client:
        admin_headers = signup_admin(client)

        # Drive a few queries through. These all hit the auth-gated /query,
        # so use the admin token (works since admins are also "authenticated").
        for q in ["Section 302 IPC?", "Article 21?", "hi", "thanks"]:
            client.post(
                "/api/v1/query",
                json={"query": q, "session_id": "ov"},
                headers=admin_headers,
            )

        r = client.get("/api/v1/admin/overview", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()

        assert body["queries"]["total"] == 4
        by_route = body["queries"]["by_route"]
        route_share = body["queries"]["route_share"]
        assert sum(by_route.values()) == 4
        # share is normalised counts/total, rounded to 4 places
        for route, count in by_route.items():
            assert abs(route_share[route] - count / 4) < 1e-6

        # Latency: at least one observation per query
        assert body["latency"]["count"] == 4
        assert body["latency"]["mean_ms"] >= 0


# ── /admin/documents ────────────────────────────────────────────────────────


@pytest.fixture
def admin_test_doc_source() -> str:
    """Per-test source name so parallel tests can't collide on chunks."""
    return "regression-admin-docs.txt"


async def _seed_document(source: str, *, versions: int = 1) -> None:
    """Ingest N text revisions for a source so the admin endpoints see chunks."""
    chunker = DocumentChunker(ChunkConfig(max_chars=400, overlap=50))
    for i in range(versions):
        await ingest_versioned_text(
            vector_store,
            chunker,
            text=f"v{i} content about contract obligations. " * 10,
            source=source,
        )


def test_documents_list_requires_admin(admin_test_doc_source):
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/documents").status_code == 401
        user_headers = signup_user(client, email="u3@example.com")
        assert (
            client.get("/api/v1/admin/documents", headers=user_headers).status_code
            == 403
        )


async def test_documents_list_returns_seeded_source(admin_test_doc_source):
    await _seed_document(admin_test_doc_source, versions=2)
    try:
        with TestClient(app) as client:
            headers = signup_admin(client, email="admin2@example.com")
            r = client.get("/api/v1/admin/documents", headers=headers)
            assert r.status_code == 200
            body = r.json()
            assert body["total"] == len(body["documents"])
            sources = [d["source"] for d in body["documents"]]
            assert admin_test_doc_source in sources
            row = next(
                d for d in body["documents"] if d["source"] == admin_test_doc_source
            )
            assert row["versions"] == 2
            assert row["chunks_total"] >= 2  # at least one chunk per version
            assert row["chunks_active"] >= 1  # latest version is active
    finally:
        await vector_store.delete_document(admin_test_doc_source)


async def test_documents_detail_shape(admin_test_doc_source):
    await _seed_document(admin_test_doc_source, versions=2)
    try:
        with TestClient(app) as client:
            headers = signup_admin(client, email="admin3@example.com")
            r = client.get(
                f"/api/v1/admin/documents/{admin_test_doc_source}", headers=headers
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["source"] == admin_test_doc_source
            assert len(body["versions"]) == 2
            superseded = [v for v in body["versions"] if v["superseded"]]
            active = [v for v in body["versions"] if not v["superseded"]]
            # Exactly one active version after the second ingest.
            assert len(active) == 1
            assert len(superseded) == 1
    finally:
        await vector_store.delete_document(admin_test_doc_source)


async def test_documents_detail_missing_404():
    with TestClient(app) as client:
        headers = signup_admin(client, email="admin4@example.com")
        r = client.get(
            "/api/v1/admin/documents/does-not-exist.txt", headers=headers
        )
        assert r.status_code == 404


async def test_documents_delete_removes_chunks(admin_test_doc_source):
    await _seed_document(admin_test_doc_source, versions=1)
    try:
        with TestClient(app) as client:
            headers = signup_admin(client, email="admin5@example.com")
            r = client.delete(
                f"/api/v1/admin/documents/{admin_test_doc_source}", headers=headers
            )
            assert r.status_code == 204, r.text
            r = client.get(
                f"/api/v1/admin/documents/{admin_test_doc_source}", headers=headers
            )
            assert r.status_code == 404
    finally:
        # In case the test errored before delete, leave a clean store behind.
        await vector_store.delete_document(admin_test_doc_source)


async def test_documents_delete_missing_404():
    with TestClient(app) as client:
        headers = signup_admin(client, email="admin6@example.com")
        r = client.delete(
            "/api/v1/admin/documents/never-existed.txt", headers=headers
        )
        assert r.status_code == 404


# ── /admin/system ───────────────────────────────────────────────────────────


def test_system_requires_admin():
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/system").status_code == 401
        user_headers = signup_user(client, email="u-sys@example.com")
        assert (
            client.get("/api/v1/admin/system", headers=user_headers).status_code
            == 403
        )


def test_system_response_shape_and_no_secret_leaks():
    """Top-level sections present, derived status reasonable, and the API
    key surface (envs, LangSmith key) is never echoed back."""
    with TestClient(app) as client:
        headers = signup_admin(client, email="admin-sys@example.com")
        r = client.get("/api/v1/admin/system", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()

        # Top-level sections present
        for key in (
            "status",
            "checks",
            "vector_store",
            "langsmith",
            "llm_providers",
            "memory",
            "process",
            "ingest_failures",
            "error_counters",
        ):
            assert key in body, f"missing top-level key {key}"

        # status is "ok" or "degraded"
        assert body["status"] in ("ok", "degraded")

        # checks is a non-empty list of {name, ok, detail}
        assert isinstance(body["checks"], list) and len(body["checks"]) >= 3
        for check in body["checks"]:
            assert "name" in check and "ok" in check and "detail" in check
            assert isinstance(check["ok"], bool)

        # Vector store shape
        vs = body["vector_store"]
        assert vs["count"] >= 0
        assert vs["embedding_dim"] > 0
        assert isinstance(vs["collection"], str)

        # Memory section reflects the singleton
        mem = body["memory"]
        for key in ("sessions", "turns_total", "max_sessions", "window"):
            assert key in mem
            assert isinstance(mem[key], int)
            assert mem[key] >= 0

        # Process section reports python version like "3.x.y"
        proc = body["process"]
        assert proc["python_version"].count(".") == 2

        # LangSmith section never carries the API key under any name.
        ls = body["langsmith"]
        for forbidden in ("api_key", "apiKey", "key", "secret"):
            assert forbidden not in ls, f"LangSmith section leaks {forbidden}"

        # LLM providers carry only model + configured flag — no key fields.
        for provider in body["llm_providers"]["providers"]:
            assert set(provider.keys()) <= {"name", "configured", "model"}
            for forbidden in ("api_key", "key", "secret"):
                assert forbidden not in provider


def test_system_memory_reflects_recorded_turns():
    """Recording a turn through the memory service shows up in /system."""
    from app.services.memory import Turn, conversation_memory

    # Use a fresh session id so we don't depend on prior state.
    session_id = "sys-test-session"
    conversation_memory.record(
        session_id,
        Turn(query="q", intent="bare_act_query", route="deterministic", subject="s"),
    )

    with TestClient(app) as client:
        headers = signup_admin(client, email="admin-sys2@example.com")
        r = client.get("/api/v1/admin/system", headers=headers)
        body = r.json()
        assert body["memory"]["sessions"] >= 1
        assert body["memory"]["turns_total"] >= 1


# ── /admin/analytics ────────────────────────────────────────────────────────


def test_analytics_requires_admin():
    with TestClient(app) as client:
        # Anonymous → 401
        assert client.get("/api/v1/admin/analytics").status_code == 401
        # Normal user → 403
        user_headers = signup_user(client, email="u-an@example.com")
        assert (
            client.get("/api/v1/admin/analytics", headers=user_headers).status_code
            == 403
        )


def test_analytics_rejects_bad_range():
    with TestClient(app) as client:
        headers = signup_admin(client, email="admin-an1@example.com")
        # FastAPI's pattern validator rejects the value at the schema layer.
        r = client.get("/api/v1/admin/analytics?range=99y", headers=headers)
        assert r.status_code == 422, r.text


def test_analytics_response_shape_empty_corpus():
    """Fresh DB → endpoint still resolves with zeroed totals + empty timeline
    rows (each bucket present, all routes at 0)."""
    with TestClient(app) as client:
        headers = signup_admin(client, email="admin-an2@example.com")
        r = client.get("/api/v1/admin/analytics?range=1h", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()

        for key in (
            "range",
            "routes",
            "timeseries",
            "intent_distribution",
            "route_share",
            "totals",
            "recent_failures",
        ):
            assert key in body, f"missing key {key}"

        assert body["range"] == "1h"
        assert body["totals"]["total"] == 0
        assert body["totals"]["errors"] == 0
        assert body["totals"]["error_rate"] == 0
        assert body["recent_failures"] == []
        # Even with no events, the timeline should still be dense across
        # buckets (the chart renders an empty 1h window).
        assert len(body["timeseries"]) >= 1
        for row in body["timeseries"]:
            assert "ts" in row


def test_query_records_event_visible_in_analytics():
    """Behaviour invariant: a /query call writes a QueryEvent row that
    shows up in the timeseries + route_share + totals."""
    with TestClient(app) as client:
        admin_headers = signup_admin(client, email="admin-an3@example.com")
        # Drive a couple of queries through (admins can hit /query too).
        for q in ["Section 302 IPC?", "Article 21?"]:
            r = client.post(
                "/api/v1/query",
                json={"query": q, "session_id": "an"},
                headers=admin_headers,
            )
            assert r.status_code == 200, r.text

        # Pull the analytics view.
        r = client.get("/api/v1/admin/analytics?range=24h", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["totals"]["total"] >= 2
        # Route share sums to total (within the window).
        assert sum(body["route_share"].values()) >= 2
        # Intent distribution contains at least one of the routes we drove.
        intents = {row["intent"] for row in body["intent_distribution"]}
        assert intents, "intent distribution should not be empty after queries"


def test_query_event_persistence_columns():
    """Direct DB check: the writer should populate intent/route/latency/
    query_preview without raising and without storing the full query text
    beyond the preview cap."""
    import asyncio

    from sqlalchemy import select

    from app.analytics import record_query_event
    from app.analytics.models import QueryEvent
    from app.db.session import create_all, session_scope

    long_query = "A" * 500

    async def run() -> dict:
        # The conftest fixture provisions a fresh SQLite per test but does
        # not run create_all (that normally happens via FastAPI lifespan).
        # Make the table ourselves so the writer has somewhere to insert.
        await create_all()
        await record_query_event(
            user_id=None,
            session_id="t",
            query=long_query,
            intent="bare_act_query",
            route="deterministic",
            confidence=0.9,
            latency_ms=12.5,
        )
        async with session_scope() as s:
            row = (
                await s.execute(
                    select(QueryEvent).order_by(QueryEvent.id.desc()).limit(1)
                )
            ).scalar_one()
            return {
                "intent": row.intent,
                "route": row.route,
                "preview_len": len(row.query_preview),
                "latency_ms": row.latency_ms,
            }

    out = asyncio.new_event_loop().run_until_complete(run())
    assert out["intent"] == "bare_act_query"
    assert out["route"] == "deterministic"
    assert 1 <= out["preview_len"] <= 160  # writer truncates
    assert out["latency_ms"] == 12.5


# ── /admin/evaluation/runs ──────────────────────────────────────────────────


def test_evaluation_runs_list_requires_admin():
    with TestClient(app) as client:
        assert client.get("/api/v1/admin/evaluation/runs").status_code == 401
        user_headers = signup_user(client, email="u-ev@example.com")
        assert (
            client.get("/api/v1/admin/evaluation/runs", headers=user_headers).status_code
            == 403
        )


def test_evaluation_run_detail_404_for_unknown_id():
    with TestClient(app) as client:
        headers = signup_admin(client, email="admin-ev1@example.com")
        r = client.get("/api/v1/admin/evaluation/runs/9999", headers=headers)
        assert r.status_code == 404


def test_evaluation_run_delete_404_for_unknown_id():
    with TestClient(app) as client:
        headers = signup_admin(client, email="admin-ev2@example.com")
        r = client.delete("/api/v1/admin/evaluation/runs/9999", headers=headers)
        assert r.status_code == 404


def test_evaluation_runs_empty_listing():
    """Fresh DB → list returns an empty array, not 404."""
    with TestClient(app) as client:
        headers = signup_admin(client, email="admin-ev3@example.com")
        r = client.get("/api/v1/admin/evaluation/runs", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["runs"] == []
        assert body["total"] == 0


def test_record_evaluation_run_persistence_and_list():
    """Behavioural invariant: writing a run via the persistence helper
    shows up in /admin/evaluation/runs, and the detail endpoint returns
    the parsed report under `report`."""
    import asyncio

    from app.evaluation.metrics import (
        EvaluationReport,
        EvaluationSummary,
        MetricSummary,
        RowResult,
    )
    from app.evaluation.persistence import record_evaluation_run

    summary = EvaluationSummary(
        dataset="t.csv",
        total_rows=2,
        scored_rows=2,
        failed_rows=0,
        f1_score=MetricSummary(mean=0.7, min=0.5, max=0.9),
        cosine_similarity=MetricSummary(mean=0.8, min=0.7, max=0.9),
        keyword_overlap=MetricSummary(mean=0.6, min=0.4, max=0.8),
        retrieval_confidence=MetricSummary(mean=0.75, min=0.7, max=0.8),
    )
    row = RowResult(
        question="What is Section 302 IPC?",
        expected_answer="Murder",
        generated_answer="Section 302 covers murder.",
        f1_score=0.9,
        cosine_similarity=0.9,
        keyword_overlap=0.8,
        retrieval_confidence=0.8,
        intent="bare_act_query",
        route="deterministic",
    )
    report = EvaluationReport(summary=summary, results=[row, row])

    with TestClient(app) as client:
        headers = signup_admin(client, email="admin-ev4@example.com")
        # Persist via the helper (the route also calls this; we exercise
        # the helper directly so we don't need to spin up the real eval
        # pipeline in tests).
        loop = asyncio.new_event_loop()
        try:
            run_id = loop.run_until_complete(
                record_evaluation_run(
                    report=report,
                    dataset_filename="t.csv",
                    name="smoke run",
                    created_by=None,
                )
            )
        finally:
            loop.close()
        assert run_id is not None

        # List endpoint sees it
        r = client.get("/api/v1/admin/evaluation/runs", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        first = body["runs"][0]
        assert first["id"] == run_id
        assert first["name"] == "smoke run"
        assert first["dataset_filename"] == "t.csv"
        assert first["total_rows"] == 2
        assert first["scored_rows"] == 2
        assert first["failed_rows"] == 0
        assert abs(first["f1_mean"] - 0.7) < 1e-6

        # Detail endpoint returns the parsed report
        r = client.get(
            f"/api/v1/admin/evaluation/runs/{run_id}", headers=headers
        )
        assert r.status_code == 200, r.text
        detail = r.json()
        assert detail["id"] == run_id
        assert detail["report"]["summary"]["dataset"] == "t.csv"
        assert len(detail["report"]["results"]) == 2

        # Delete + verify gone
        r = client.delete(
            f"/api/v1/admin/evaluation/runs/{run_id}", headers=headers
        )
        assert r.status_code == 204
        r = client.get(
            f"/api/v1/admin/evaluation/runs/{run_id}", headers=headers
        )
        assert r.status_code == 404


# ── /admin/documents/upload ─────────────────────────────────────────────────


_PLAIN_TEXT_BYTES = (
    b"Section 42. Universal rights.\n\nEvery person enjoys the inalienable "
    b"right to a fair hearing under the principles of natural justice. "
    b"This section is paraphrased solely for ingestion-pipeline testing."
)


def test_documents_upload_requires_auth():
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/admin/documents/upload",
            files=[("file", ("test.txt", _PLAIN_TEXT_BYTES, "text/plain"))],
        )
        assert r.status_code == 401


def test_documents_upload_rejects_non_admin():
    with TestClient(app) as client:
        headers = signup_user(client, email="u-upload@example.com")
        r = client.post(
            "/api/v1/admin/documents/upload",
            files=[("file", ("test.txt", _PLAIN_TEXT_BYTES, "text/plain"))],
            headers=headers,
        )
        assert r.status_code == 403


async def test_documents_upload_admin_happy_path():
    source = "regression-admin-upload.txt"
    try:
        with TestClient(app) as client:
            headers = signup_admin(client, email="admin-up@example.com")
            r = client.post(
                "/api/v1/admin/documents/upload",
                files=[("file", (source, _PLAIN_TEXT_BYTES, "text/plain"))],
                headers=headers,
            )
            assert r.status_code == 200, r.text
            body = r.json()

            # Shape contract operators rely on
            for key in (
                "source",
                "stored_as",
                "status",
                "chunks_created",
                "chunks_superseded",
                "version",
                "version_id",
                "is_new_version",
                "file_size",
                "word_count",
                "char_count",
                "latency_ms",
            ):
                assert key in body, f"missing {key} in upload response"

            assert body["source"] == source
            assert body["status"] == "ingested"
            assert body["is_new_version"] is True
            assert body["version"] == 1
            assert body["chunks_created"] >= 1
            assert body["chunks_superseded"] == 0
            assert body["latency_ms"] > 0
            assert body["file_size"] == len(_PLAIN_TEXT_BYTES)
    finally:
        # Clean the corpus regardless of test outcome — keeps cross-test
        # isolation intact (vector_store is module-scoped, not per-test).
        from app.rag.vector_store import vector_store

        await vector_store.delete_document(source)


def test_documents_upload_rejects_unsupported_extension():
    with TestClient(app) as client:
        headers = signup_admin(client, email="admin-up2@example.com")
        r = client.post(
            "/api/v1/admin/documents/upload",
            files=[
                (
                    "file",
                    ("evil.exe", b"\x7fELF\x02\x01", "application/x-msdownload"),
                )
            ],
            headers=headers,
        )
        assert r.status_code == 415, r.text
        assert "Unsupported file type" in r.json()["detail"]


def test_documents_upload_rejects_empty_text():
    """A 0-byte upload (or any file whose parser yields no text) returns
    422 rather than silently creating a zero-chunk source."""
    with TestClient(app) as client:
        headers = signup_admin(client, email="admin-up3@example.com")
        r = client.post(
            "/api/v1/admin/documents/upload",
            files=[("file", ("empty.txt", b"", "text/plain"))],
            headers=headers,
        )
        assert r.status_code == 422, r.text


async def test_documents_upload_then_visible_in_list():
    """End-to-end: upload → /admin/documents lists the new source."""
    source = "regression-admin-upload-listing.md"
    try:
        with TestClient(app) as client:
            headers = signup_admin(client, email="admin-up4@example.com")
            r = client.post(
                "/api/v1/admin/documents/upload",
                files=[("file", (source, _PLAIN_TEXT_BYTES, "text/markdown"))],
                headers=headers,
            )
            assert r.status_code == 200, r.text

            r = client.get("/api/v1/admin/documents", headers=headers)
            assert r.status_code == 200
            sources = [d["source"] for d in r.json()["documents"]]
            assert source in sources, sources
    finally:
        from app.rag.vector_store import vector_store

        await vector_store.delete_document(source)


async def test_documents_upload_is_idempotent_on_same_content():
    """Re-uploading the same content reports status="noop" + chunks_created=0."""
    source = "regression-admin-upload-idempotent.txt"
    try:
        with TestClient(app) as client:
            headers = signup_admin(client, email="admin-up5@example.com")
            r1 = client.post(
                "/api/v1/admin/documents/upload",
                files=[("file", (source, _PLAIN_TEXT_BYTES, "text/plain"))],
                headers=headers,
            )
            assert r1.status_code == 200
            assert r1.json()["status"] == "ingested"

            r2 = client.post(
                "/api/v1/admin/documents/upload",
                files=[("file", (source, _PLAIN_TEXT_BYTES, "text/plain"))],
                headers=headers,
            )
            assert r2.status_code == 200
            body = r2.json()
            assert body["status"] == "noop"
            assert body["is_new_version"] is False
            assert body["chunks_created"] == 0
    finally:
        from app.rag.vector_store import vector_store

        await vector_store.delete_document(source)
