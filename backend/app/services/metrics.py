"""In-process metrics aggregator with OTel/Prometheus-ready interface.

Captures counters and latency histograms that the rest of the codebase
calls into at meaningful boundaries (routing, ingestion, retrieval, …).
A snapshot is exposed at ``GET /api/v1/metrics``; a Prometheus text
exposition is exposed at ``GET /api/v1/metrics/prometheus`` for any
operator that wants to scrape from a single-node deployment.

Why this shape
--------------
The original module exposed three functions: ``inc``, ``observe``,
``timer``. They worked, but they bound every call site to the in-process
registry — a swap to OpenTelemetry / Prometheus would have meant a
search-and-replace across the codebase.

This iteration introduces two protocol-shaped objects — :class:`Counter`
and :class:`Histogram` — that mirror the OTel SDK surface (``.add()`` /
``.record()``) closely enough that a future swap can be one file:
re-implement ``MetricsRegistry`` with an OTel ``MeterProvider`` and the
rest of the codebase keeps compiling.

For backward compatibility, the module continues to export ``inc``,
``observe``, and ``timer`` as thin wrappers — every existing call site
still works. New code should prefer the ``counter(...)`` / ``histogram(...)``
factories.

Design constraints (preserved)
------------------------------
- **Thread- and async-safe.** A single ``threading.Lock`` guards every
  mutation. The work inside the lock is microseconds (one dict update);
  contention is not a practical concern at LawFlow's scale.
- **Bounded memory.** Latency arrays are capped at
  :data:`_LATENCY_WINDOW` entries — older samples are dropped FIFO so a
  long-running process can't leak unbounded memory.
- **No external dependencies.** Pure Python; we want this to survive a
  Prometheus / OpenTelemetry decision being deferred.

Public API
----------
- :class:`Counter`           inc(by=1, **tags)
- :class:`Histogram`         observe(value, **tags) + timer() ctxmgr
- :func:`counter(name)`      build / fetch a Counter
- :func:`histogram(name)`    build / fetch a Histogram
- :func:`inc`, :func:`observe`, :func:`timer`   legacy thin-wrappers
- :func:`snapshot()`         JSON-serialisable view
- :func:`prometheus_text()`  Prometheus text-exposition v0.0.4
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any

# Maximum number of recent samples retained per histogram. 10k samples
# at the worst-case rate of 100 req/s = 100 s of history — enough to
# compute meaningful p50/p95.
_LATENCY_WINDOW: int = 10_000


def _tag_suffix(tags: dict[str, Any]) -> str:
    """Build a deterministic dotted suffix from a tag dict."""
    if not tags:
        return ""
    parts = []
    for k in sorted(tags):
        v = tags[k]
        if v is None or v == "":
            continue
        parts.append(f"{k}={v}")
    return ("." + ".".join(parts)) if parts else ""


# ── Observable abstractions ──────────────────────────────────────────────


class Counter:
    """Monotonic counter.

    Mirrors ``opentelemetry.metrics.Counter`` so a future swap can map
    ``add()`` 1:1. ``inc()`` is preserved as the historical method name.
    """

    __slots__ = ("_name", "_registry")

    def __init__(self, name: str, registry: "MetricsRegistry") -> None:
        self._name = name
        self._registry = registry

    @property
    def name(self) -> str:
        return self._name

    def inc(self, by: int = 1, **tags: Any) -> None:
        self._registry._inc(self._name, by=by, **tags)

    # OTel-compatible alias.
    def add(self, amount: int = 1, **tags: Any) -> None:  # pragma: no cover — alias
        self._registry._inc(self._name, by=amount, **tags)


class Histogram:
    """Sample distribution. Records latency, sizes, scores.

    Mirrors ``opentelemetry.metrics.Histogram`` so a future swap can map
    ``record()`` 1:1. ``observe()`` is preserved as the historical method
    name; ``timer()`` returns an async context manager that records
    elapsed milliseconds.
    """

    __slots__ = ("_name", "_registry")

    def __init__(self, name: str, registry: "MetricsRegistry") -> None:
        self._name = name
        self._registry = registry

    @property
    def name(self) -> str:
        return self._name

    def observe(self, value: float, **tags: Any) -> None:
        self._registry._observe(self._name, value, **tags)

    # OTel-compatible alias.
    def record(self, value: float, **tags: Any) -> None:  # pragma: no cover — alias
        self._registry._observe(self._name, value, **tags)

    @asynccontextmanager
    async def timer(self, **tags: Any):
        """Time an async block; record the elapsed time as milliseconds."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._registry._observe(self._name, elapsed_ms, **tags)


class MetricsRegistry:
    """Process-wide metric registry — created once per import.

    Holds both the raw storage and the lightweight Counter / Histogram
    handles. Handles are cached by name so repeated lookups are free.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._samples: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=_LATENCY_WINDOW)
        )
        self._counter_handles: dict[str, Counter] = {}
        self._histogram_handles: dict[str, Histogram] = {}
        self._started_at: float = time.time()

    # ── Handle factories ────────────────────────────────────────────────

    def counter(self, name: str) -> Counter:
        """Get-or-create the named Counter handle (idempotent)."""
        h = self._counter_handles.get(name)
        if h is None:
            h = Counter(name, self)
            self._counter_handles[name] = h
        return h

    def histogram(self, name: str) -> Histogram:
        """Get-or-create the named Histogram handle (idempotent)."""
        h = self._histogram_handles.get(name)
        if h is None:
            h = Histogram(name, self)
            self._histogram_handles[name] = h
        return h

    # ── Backwards-compatible API (delegates to handles) ────────────────

    def inc(self, name: str, by: int = 1, **tags: Any) -> None:
        """Increment ``name`` (optionally tagged) by ``by``."""
        self._inc(name, by=by, **tags)

    def observe(self, name: str, value: float, **tags: Any) -> None:
        """Record one observation for ``name``. Bounded FIFO history."""
        self._observe(name, value, **tags)

    @asynccontextmanager
    async def timer(self, name: str, **tags: Any):
        """Time an async block; record the elapsed time as milliseconds."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self._observe(name, elapsed_ms, **tags)

    # ── Storage (internal — Counter / Histogram delegate here) ────────

    def _inc(self, name: str, *, by: int = 1, **tags: Any) -> None:
        full = name + _tag_suffix(tags)
        with self._lock:
            self._counters[full] += int(by)

    def _observe(self, name: str, value: float, **tags: Any) -> None:
        full = name + _tag_suffix(tags)
        with self._lock:
            self._samples[full].append(float(value))

    # ── Snapshot / Prometheus ───────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable view of current metrics."""
        with self._lock:
            counters = dict(sorted(self._counters.items()))
            histograms: dict[str, dict[str, Any]] = {}
            for name, samples in sorted(self._samples.items()):
                if not samples:
                    continue
                histograms[name] = _summarise(list(samples))
            uptime = time.time() - self._started_at
        return {
            "uptime_seconds": round(uptime, 2),
            "counters": counters,
            "histograms": histograms,
        }

    def prometheus_text(self) -> str:
        """Render the current metrics in Prometheus text-exposition v0.0.4.

        Counters get the ``_total`` suffix Prometheus convention requires
        (an aggregating Prometheus server expects monotonic counters to
        end in ``_total``). Histograms emit five lines each: count, sum-
        approximated (count * mean), and three quantile observations.
        Tags encoded into the metric name (``foo.bar=baz``) become
        Prometheus labels (``foo{bar="baz"}``).
        """
        out: list[str] = []
        with self._lock:
            counters = dict(self._counters)
            samples = {n: list(s) for n, s in self._samples.items() if s}

        # Counters
        emitted_counter_help: set[str] = set()
        for full, val in sorted(counters.items()):
            base, labels = _split_tags(full)
            metric = _sanitise(base) + "_total"
            if metric not in emitted_counter_help:
                out.append(f"# HELP {metric} LawFlow counter")
                out.append(f"# TYPE {metric} counter")
                emitted_counter_help.add(metric)
            out.append(f"{metric}{labels} {int(val)}")

        # Histograms — surface count/p50/p95/max as separate gauges so the
        # text exposition is meaningful without a Prometheus histogram
        # server. The next iteration of this module (when OTel backs the
        # registry) can emit a proper histogram with buckets.
        emitted_hist_help: set[str] = set()
        for full, vals in sorted(samples.items()):
            base, labels = _split_tags(full)
            metric = _sanitise(base)
            summary = _summarise(vals)
            for stat in ("count", "mean", "p50", "p95", "max"):
                name = f"{metric}_{stat}"
                if name not in emitted_hist_help:
                    out.append(f"# HELP {name} LawFlow histogram {stat}")
                    out.append(f"# TYPE {name} gauge")
                    emitted_hist_help.add(name)
                out.append(f"{name}{labels} {summary[stat]}")

        # Uptime gauge
        out.append("# HELP lawflow_uptime_seconds Process uptime in seconds")
        out.append("# TYPE lawflow_uptime_seconds gauge")
        out.append(
            f"lawflow_uptime_seconds {round(time.time() - self._started_at, 2)}"
        )

        # Prometheus requires a trailing newline.
        return "\n".join(out) + "\n"

    def reset(self) -> None:
        """Drop all counters + samples (test helper, not exposed via API)."""
        with self._lock:
            self._counters.clear()
            self._samples.clear()
            self._started_at = time.time()


def _summarise(values: list[float]) -> dict[str, Any]:
    """count / mean / p50 / p95 / max for a histogram-like metric."""
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    return {
        "count": n,
        "mean": round(sum(sorted_vals) / n, 3),
        "p50": round(_quantile(sorted_vals, 0.5), 3),
        "p95": round(_quantile(sorted_vals, 0.95), 3),
        "max": round(sorted_vals[-1], 3),
    }


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    # Use the bisect-based "lower" estimate — good enough for ops dashboards.
    idx = min(len(sorted_vals) - 1, int(q * len(sorted_vals)))
    return float(sorted_vals[idx])


# ── Prometheus name helpers ───────────────────────────────────────────────


def _sanitise(name: str) -> str:
    """Coerce a LawFlow metric name into a Prometheus-legal identifier.

    Prom allows ``[a-zA-Z_:][a-zA-Z0-9_:]*``. The codebase uses dots in
    metric names; the historical reader doesn't care, but Prom does.
    """
    out = []
    for i, ch in enumerate(name):
        if ch.isalnum() or ch in "_:":
            out.append(ch)
        else:
            out.append("_")
    if out and out[0].isdigit():
        out.insert(0, "_")
    return "".join(out) or "metric"


def _split_tags(full: str) -> tuple[str, str]:
    """Pull tag pairs out of the encoded suffix; return (base, " {k=v}").

    Counters are stored as ``base.k=v.j=w``. We split on the *first* tag
    pair (key=value) and treat everything before it as the base metric.
    """
    parts = full.split(".")
    base_parts: list[str] = []
    tag_parts: list[tuple[str, str]] = []
    for p in parts:
        if "=" in p and base_parts:
            k, _, v = p.partition("=")
            tag_parts.append((k, v))
        else:
            base_parts.append(p)
    base = ".".join(base_parts)
    if not tag_parts:
        return base, ""
    label_str = ",".join(
        f'{_sanitise(k)}="{_escape_label_value(v)}"' for k, v in tag_parts
    )
    return base, "{" + label_str + "}"


def _escape_label_value(v: str) -> str:
    """Prometheus label-value escape rules: backslash, double-quote, newline."""
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# ── Module-level singleton + back-compat shims ───────────────────────────


metrics: MetricsRegistry = MetricsRegistry()


# Convenience top-level functions kept for backward compat. New code can
# prefer ``metrics.counter("…")`` and ``metrics.histogram("…")``.


def inc(name: str, by: int = 1, **tags: Any) -> None:  # pragma: no cover — shim
    metrics.inc(name, by=by, **tags)


def observe(name: str, value: float, **tags: Any) -> None:  # pragma: no cover — shim
    metrics.observe(name, value, **tags)


@asynccontextmanager
async def timer(name: str, **tags: Any):  # pragma: no cover — shim
    async with metrics.timer(name, **tags):
        yield


def counter(name: str) -> Counter:
    """Get-or-create a Counter handle from the global registry."""
    return metrics.counter(name)


def histogram(name: str) -> Histogram:
    """Get-or-create a Histogram handle from the global registry."""
    return metrics.histogram(name)


__all__ = [
    "Counter",
    "Histogram",
    "MetricsRegistry",
    "counter",
    "histogram",
    "inc",
    "metrics",
    "observe",
    "timer",
]
