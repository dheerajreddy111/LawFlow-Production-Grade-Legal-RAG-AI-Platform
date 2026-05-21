"""Retrieval benchmark — vector-only baseline vs. hybrid pipeline.

The aggregate metrics in ``app/evaluation`` already drive the end-to-end
pipeline (LegalService.process_query → RAGEngine.answer → LLM); they
exercise generation quality, not retrieval quality in isolation. This
script measures retrieval quality directly: how often does the *correct
provision* land in the top-k?

Methodology
-----------
For each question in ``evaluations/legal_retrieval_v1.csv``:

  1. Run the OLD path: a single ``VectorStore.similarity_search`` with
     ``RAG_RETRIEVE_K`` results. No hybrid, no rewrite, no rerank.

  2. Run the NEW path: ``app.rag.retrieval.retrieve`` with the same
     ``top_k``.

We score retrieval against the **expected_answer** text by token
overlap (a cheap proxy for "did we surface the right provision?") plus
a "name match" check that looks for the act + section number in the
top-1 source string. The benchmark deliberately uses both because
token-overlap alone can be gamed by long expected-answer strings.

Output
------
JSON to stdout (or ``--output`` path) with per-question detail and
aggregate deltas. Suitable for checking into the docs as a baseline
snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from pathlib import Path

# Ensure backend importable when invoked from anywhere.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


_WORD = re.compile(r"[a-z0-9]+", re.I)


def _toks(text: str) -> set[str]:
    return {t.lower() for t in _WORD.findall(text or "") if len(t) > 2}


def _overlap(generated: str, expected: str) -> float:
    a, b = _toks(generated), _toks(expected)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(b)  # recall-like (cheap proxy)


def _name_match(source: str, expected: str) -> bool:
    """Does the chunk's source string mention what the expected answer cites?"""
    src_low = source.lower()
    exp_low = expected.lower()
    # Pull section/article numbers from the expected text and check the source.
    for m in re.finditer(r"(?:section|article|art\.)\s+(\d{1,4}[a-z]?)", exp_low):
        n = m.group(1)
        # Source uses "Section 25F" or "Article 21" verbatim.
        if re.search(rf"(?:section|article)\s+{re.escape(n)}\b", src_low):
            return True
    return False


async def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=_BACKEND.parent / "evaluations" / "legal_retrieval_v1.csv",
        help="CSV with question,expected_answer columns.",
    )
    parser.add_argument(
        "--top-k", type=int, default=4, help="top-k for both paths"
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="Write JSON report here"
    )
    args = parser.parse_args()

    from app.rag.bm25 import bm25_index
    from app.rag.ingest import ingest_corpora
    from app.rag.retrieval import retrieve
    from app.rag.vector_store import vector_store

    print("[bench] ingesting corpus + warming BM25 ...", flush=True)
    await ingest_corpora()
    await bm25_index().refresh()
    print(
        f"[bench] corpus ready: {(await vector_store.collection_stats()).get('count')} chunks",
        flush=True,
    )

    rows = list(csv.DictReader(args.dataset.open()))
    print(f"[bench] {len(rows)} questions", flush=True)

    per_q: list[dict] = []
    base_overlap, base_match, base_latency = 0.0, 0, 0.0
    new_overlap, new_match, new_latency = 0.0, 0, 0.0

    for i, row in enumerate(rows, start=1):
        q, expected = row["question"], row["expected_answer"]

        # OLD path — vector-only.
        t = time.perf_counter()
        base_hits = await vector_store.similarity_search(q, top_k=args.top_k)
        base_lat = (time.perf_counter() - t) * 1000
        base_text = "\n".join(h.text for h in base_hits)
        base_top_source = base_hits[0].source if base_hits else ""
        b_overlap = _overlap(base_text, expected)
        b_match = _name_match(base_top_source, expected)

        # NEW path — hybrid orchestrator.
        t = time.perf_counter()
        new_result = await retrieve(q, top_k=args.top_k)
        new_lat = (time.perf_counter() - t) * 1000
        new_text = "\n".join(c.text for c in new_result.chunks)
        new_top_source = new_result.chunks[0].source if new_result.chunks else ""
        n_overlap = _overlap(new_text, expected)
        n_match = _name_match(new_top_source, expected)

        per_q.append(
            {
                "id": i,
                "question": q,
                "baseline_top_source": base_top_source,
                "baseline_overlap": round(b_overlap, 3),
                "baseline_name_match": b_match,
                "baseline_latency_ms": round(base_lat, 1),
                "new_top_source": new_top_source,
                "new_overlap": round(n_overlap, 3),
                "new_name_match": n_match,
                "new_latency_ms": round(new_lat, 1),
                "delta_overlap": round(n_overlap - b_overlap, 3),
            }
        )
        base_overlap += b_overlap
        base_match += int(b_match)
        base_latency += base_lat
        new_overlap += n_overlap
        new_match += int(n_match)
        new_latency += new_lat

        status = "✓" if n_overlap >= b_overlap else "↓"
        print(
            f"[{i:2d}/{len(rows)}] {status}  base={b_overlap:.2f} new={n_overlap:.2f}  {q[:60]}",
            flush=True,
        )

    n = len(rows) or 1
    summary = {
        "n_questions": n,
        "top_k": args.top_k,
        "baseline": {
            "mean_overlap": round(base_overlap / n, 4),
            "name_match_rate": round(base_match / n, 4),
            "mean_latency_ms": round(base_latency / n, 1),
        },
        "new": {
            "mean_overlap": round(new_overlap / n, 4),
            "name_match_rate": round(new_match / n, 4),
            "mean_latency_ms": round(new_latency / n, 1),
        },
        "delta": {
            "mean_overlap": round((new_overlap - base_overlap) / n, 4),
            "name_match_rate": round((new_match - base_match) / n, 4),
            "mean_latency_ms": round((new_latency - base_latency) / n, 1),
        },
        "per_question": per_q,
    }

    out = json.dumps(summary, indent=2)
    if args.output:
        args.output.write_text(out)
        print(f"[bench] wrote {args.output}", flush=True)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.new_event_loop().run_until_complete(run()))
