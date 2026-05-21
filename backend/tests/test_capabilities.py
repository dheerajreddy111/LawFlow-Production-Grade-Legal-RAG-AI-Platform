"""Regression tests for the enterprise capability additions.

Covers:

- Phase A — CSV, XLSX, image OCR parsers; URL ingestion endpoint wiring
- Phase B — document versioning (idempotent re-ingest, supersession,
  active-version filter, ``GET /versions``)
- Phase C — enhanced right rail (intent-shaped suggestions, next_actions,
  help_text, examples)
- Phase D — metrics endpoint shape

LLM-dependent assertions are gated behind the ``needs_llm`` mark from
``conftest`` so a CI without secrets still passes.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest

# ── Phase A: parsers ────────────────────────────────────────────────────────


async def test_csv_parser_row_metadata():
    from app.ingestion.parsers.csv import CSVParser

    csv_text = (
        "Section,Title,Punishment\n"
        "302,Murder,Death or life imprisonment\n"
        "420,Cheating,Imprisonment up to 7 years\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(csv_text)
        path = Path(f.name)
    try:
        result = await CSVParser().parse(path)
    finally:
        path.unlink()

    assert "Section: 302" in result.text
    assert "Title: Murder" in result.text
    assert result.extra["row_count"] == 2
    assert result.extra["has_header"] is True
    assert result.extra["columns"] == ["Section", "Title", "Punishment"]


async def test_xlsx_parser_sheet_and_row_metadata():
    from openpyxl import Workbook

    from app.ingestion.parsers.xlsx import XLSXParser

    wb = Workbook()
    ws = wb.active
    ws.title = "Penalties"
    ws.append(["Section", "Fine"])
    ws.append([177, 500])
    ws.append([184, 1000])
    ws2 = wb.create_sheet("Notes")
    ws2.append(["Heading", "Detail"])
    ws2.append(["MV Act", "Drink-driving fines doubled in 2019"])

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path = Path(f.name)
    wb.save(path)
    try:
        result = await XLSXParser().parse(path)
    finally:
        path.unlink()

    assert "SHEET: Penalties" in result.text
    assert "SHEET: Notes" in result.text
    assert result.extra["sheet_count"] == 2
    # Penalties: 2 data rows (Section/Fine header + 2 rows)
    # Notes:     1 data row (Heading/Detail header + 1 row)
    assert result.extra["row_count_total"] == 3
    # And we can introspect per-sheet metadata
    sheets_by_name = {s["sheet"]: s for s in result.extra["sheets"]}
    assert sheets_by_name["Penalties"]["row_count"] == 2
    assert sheets_by_name["Notes"]["row_count"] == 1


async def test_image_parser_ocrs_text():
    """OCR engine must read printed text from a synthetic image."""
    from PIL import Image, ImageDraw

    from app.ingestion.ocr import ocr_unavailable
    from app.ingestion.parsers.image import ImageParser

    if ocr_unavailable():
        pytest.skip("OCR engine not installed — skipping OCR parser test")

    img = Image.new("RGB", (700, 80), "white")
    ImageDraw.Draw(img).text((10, 25), "Section 302 IPC Murder", fill="black")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = Path(f.name)
    img.save(path)
    try:
        result = await ImageParser().parse(path)
    finally:
        path.unlink()

    assert "Section 302" in result.text
    assert result.extra["ocr"] is True
    assert result.page_count == 1


async def test_upload_endpoint_accepts_new_extensions():
    """Uploading a CSV through the FastAPI endpoint returns parser_extras."""
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.conftest import signup_admin

    csv_bytes = b"Section,Title\n302,Murder\n420,Cheating\n"
    with TestClient(app) as client:
        headers = signup_admin(client)
        resp = client.post(
            "/api/v1/documents/upload",
            files={"file": ("sections.csv", csv_bytes, "text/csv")},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "parser_extras" in body["metadata"]
        assert body["metadata"]["parser_extras"]["row_count"] == 2


# ── Phase B: document versioning ────────────────────────────────────────────


async def test_versioned_ingest_full_cycle():
    """End-to-end: idempotent same-content, supersession on change, version list."""
    from app.rag.chunker import ChunkConfig, DocumentChunker
    from app.rag.vector_store import vector_store
    from app.rag.versioning import ingest_versioned_text

    chunker = DocumentChunker(ChunkConfig(max_chars=400, overlap=50))
    source = "regression-test-versioning.txt"
    try:
        # v1
        r1 = await ingest_versioned_text(
            vector_store,
            chunker,
            text="Initial body of text about contract obligations. " * 4,
            source=source,
        )
        assert r1.is_new_version
        assert r1.version == 1
        assert r1.chunks_added >= 1

        # v1 again — idempotent no-op
        r1b = await ingest_versioned_text(
            vector_store,
            chunker,
            text="Initial body of text about contract obligations. " * 4,
            source=source,
        )
        assert r1b.is_new_version is False
        assert r1b.chunks_added == 0

        # v2 — new content
        r2 = await ingest_versioned_text(
            vector_store,
            chunker,
            text="REVISED body of text about contract obligations. " * 4,
            source=source,
        )
        assert r2.is_new_version
        assert r2.version == 2
        assert r2.chunks_superseded >= 1

        # Versions API
        versions = await vector_store.versions_for(source)
        assert len(versions) == 2
        # Newest non-superseded first
        assert versions[0]["superseded"] is False
        assert versions[0]["version_id"] == r2.version_id
        assert versions[1]["superseded"] is True
        assert versions[1]["version_id"] == r1.version_id

        # Default search returns only v2
        active = await vector_store.similarity_search(
            "contract obligations REVISED",
            top_k=10,
            where={"source": source},
        )
        assert active, "active retrieval should find v2"
        for hit in active:
            assert hit.metadata.get("superseded") is not True

        # include_superseded=True returns both
        all_hits = await vector_store.similarity_search(
            "contract obligations",
            top_k=20,
            where={"source": source},
            include_superseded=True,
        )
        assert len(all_hits) >= 2
    finally:
        await vector_store.delete_document(source)


async def test_versions_endpoint():
    """GET /api/v1/documents/versions returns the version list."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.rag.chunker import ChunkConfig, DocumentChunker
    from app.rag.vector_store import vector_store
    from app.rag.versioning import ingest_versioned_text
    from tests.conftest import signup_user

    chunker = DocumentChunker(ChunkConfig(max_chars=400, overlap=50))
    source = "regression-test-versions-endpoint.txt"
    try:
        await ingest_versioned_text(
            vector_store, chunker, text="hello world " * 30, source=source
        )
        with TestClient(app) as client:
            headers = signup_user(client)
            r = client.get(
                f"/api/v1/documents/versions?source={source}",
                headers=headers,
            )
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["source"] == source
            assert len(data["versions"]) == 1
            v = data["versions"][0]
            assert v["superseded"] is False
            assert v["chunk_count"] >= 1
            assert v["version_id"]
    finally:
        await vector_store.delete_document(source)


# ── Phase C: enhanced right rail ────────────────────────────────────────────


async def test_right_rail_bare_act_intent_shaping():
    """BARE_ACT_QUERY intent surfaces section-focused follow-ups."""
    from app.services.legal_service import LegalService

    svc = LegalService()
    r = await svc.process_query(
        "What does Section 302 IPC say?", session_id="rr-bare"
    )
    assert r["intent"] == "bare_act_query"
    assert r["help_text"]
    assert r["next_actions"]
    assert r["examples"]
    # Intent-shaped prompt should appear before the generic domain example.
    assert any(
        s.lower().startswith(("what is the punishment under", "what are the leading"))
        for s in r["suggestions"]
    )


async def test_right_rail_legal_research_intent_shaping():
    """LEGAL_RESEARCH surfaces case-law / interpretation prompts."""
    from app.services.legal_service import LegalService

    svc = LegalService()
    r = await svc.process_query(
        "Can the police arrest someone without a warrant?",
        session_id="rr-research",
    )
    assert r["intent"] == "legal_research"
    assert any(
        "leading cases" in s.lower() or "interpret" in s.lower()
        for s in r["suggestions"]
    )
    assert r["next_actions"]
    assert r["help_text"]


async def test_right_rail_conversation_is_empty():
    """Conversation route returns empty right-rail fields."""
    from app.services.legal_service import LegalService

    svc = LegalService()
    r = await svc.process_query("hi", session_id="rr-convo")
    assert r["route"] == "conversation"
    assert r["help_text"] is None
    assert r["next_actions"] == []
    assert r["examples"] == []


async def test_sse_meta_includes_right_rail_fields():
    """SSE meta event must carry the new right-rail fields (additive)."""
    import json

    from app.services.legal_service import LegalService
    from app.services.streaming import query_event_stream

    svc = LegalService()

    async def process(q: str) -> dict:
        return await svc.process_query(q, session_id="rr-sse")

    events: list[tuple[str, dict]] = []
    async for frame in query_event_stream("Section 420 IPC?", process):
        lines = frame.strip().split("\n", 1)
        name = lines[0][len("event: "):]
        data = json.loads(lines[1][len("data: "):])
        events.append((name, data))
        if name == "meta":
            break

    meta = next(d for n, d in events if n == "meta")
    assert "help_text" in meta
    assert "next_actions" in meta
    assert "examples" in meta


# ── Phase D: metrics endpoint ────────────────────────────────────────────────


async def test_metrics_endpoint_returns_counters_and_histograms():
    """After a few queries, /api/v1/metrics returns populated counters."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.metrics import metrics
    from tests.conftest import signup_admin

    metrics.reset()

    with TestClient(app) as client:
        admin_headers = signup_admin(client)
        for q in ["Section 302 IPC?", "Can police arrest?", "hi", "thanks"]:
            client.post(
                "/api/v1/query",
                json={"query": q, "session_id": "m"},
                headers=admin_headers,
            )

        r = client.get("/api/v1/metrics", headers=admin_headers)
        assert r.status_code == 200
        snap = r.json()
        assert "uptime_seconds" in snap
        # Counters
        assert snap["counters"].get("queries_total") == 4
        # Tagged route counters present
        route_keys = [k for k in snap["counters"] if k.startswith("queries_by_route.")]
        assert route_keys, "expected per-route counters"
        # Histograms
        assert "process_query_ms" in snap["histograms"]
        h = snap["histograms"]["process_query_ms"]
        assert h["count"] == 4
        assert h["mean"] >= 0
        assert h["p50"] >= 0
        assert h["p95"] >= 0


async def test_metrics_ingestion_counter_increments_on_upload():
    """An upload increments the ext-tagged ingest counter."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.metrics import metrics
    from tests.conftest import signup_admin

    metrics.reset()
    csv_bytes = b"a,b\n1,2\n3,4\n"
    with TestClient(app) as client:
        admin_headers = signup_admin(client)
        r = client.post(
            "/api/v1/documents/upload",
            files={"file": ("t.csv", csv_bytes, "text/csv")},
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text

        snap = client.get("/api/v1/metrics", headers=admin_headers).json()
        ext_keys = [k for k in snap["counters"] if k.startswith("ingest_total.")]
        assert ext_keys, snap["counters"]
        assert "ingest_total.ext=csv" in snap["counters"]
        assert "ingest_bytes.ext=csv" in snap["histograms"]
