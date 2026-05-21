"""Metrics module — tests for the OTel-shaped Counter / Histogram
interface, the legacy ``inc`` / ``observe`` / ``timer`` shims, and the
Prometheus text-exposition output.

These run without HTTP — the goal is to lock down the public contract
of ``app.services.metrics`` so future swaps (OTel / Prom client) can be
validated against the same shape.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.metrics import (
    Counter,
    Histogram,
    counter,
    histogram,
    inc,
    metrics,
    observe,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def _reset_registry():
    metrics.reset()
    yield
    metrics.reset()


def test_counter_handle_increments_via_inc_and_add():
    c = counter("test_requests")
    assert isinstance(c, Counter)
    c.inc()
    c.inc(by=3, route="rag")
    c.add(2, route="rag")  # OTel-style alias

    snap = metrics.snapshot()
    assert snap["counters"]["test_requests"] == 1
    # tagged increments aggregate under the tag-suffixed key
    assert snap["counters"]["test_requests.route=rag"] == 5


def test_histogram_handle_records_values_and_summarises():
    h = histogram("test_latency_ms")
    assert isinstance(h, Histogram)
    for v in [10.0, 20.0, 30.0, 100.0]:
        h.observe(v)
    snap = metrics.snapshot()
    s = snap["histograms"]["test_latency_ms"]
    assert s["count"] == 4
    assert s["max"] == 100.0
    assert s["mean"] > 0


def test_histogram_timer_records_elapsed_ms():
    h = histogram("test_block_ms")

    async def workload() -> None:
        async with h.timer():
            await asyncio.sleep(0.005)

    _run(workload())
    snap = metrics.snapshot()
    assert snap["histograms"]["test_block_ms"]["count"] == 1
    assert snap["histograms"]["test_block_ms"]["max"] >= 5.0


def test_legacy_shims_still_work():
    inc("legacy_counter", by=2)
    observe("legacy_hist", 42.5)
    snap = metrics.snapshot()
    assert snap["counters"]["legacy_counter"] == 2
    assert snap["histograms"]["legacy_hist"]["count"] == 1


def test_prometheus_text_renders_well_known_format():
    counter("queries_total").inc()
    counter("queries_total").inc(route="rag")
    histogram("process_query_ms").observe(120.0)

    text = metrics.prometheus_text()
    # Each metric must be preceded by a HELP and TYPE line.
    assert "# HELP queries_total_total" in text
    assert "# TYPE queries_total_total counter" in text
    # Tagged counter renders as a labelled metric line.
    assert 'queries_total_total{route="rag"} 1' in text
    # Histogram renders count / mean / p50 / p95 / max gauges.
    for stat in ("count", "mean", "p50", "p95", "max"):
        assert f"process_query_ms_{stat}" in text
    # Trailing newline (Prom requires it).
    assert text.endswith("\n")
    # Always exposes uptime
    assert "lawflow_uptime_seconds " in text


def test_counter_handles_are_cached_and_identical():
    a = counter("dedup")
    b = counter("dedup")
    assert a is b  # cheap idempotent factory


def test_histogram_handles_are_cached_and_identical():
    a = histogram("dedup")
    b = histogram("dedup")
    assert a is b
