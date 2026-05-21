"""Benchmark CSV ↔ live-corpus alignment checker.

A benchmark row only produces useful F1 / cosine numbers when the
expected_answer is actually retrievable from the indexed corpus.
Rows that target an Act we don't carry — or a section number that
doesn't exist — score zero on retrieval and drag down the aggregate
in misleading ways.

This script:

  1. Loads the CSV.
  2. For each row, looks at the expected_answer for Act / Section /
     Article references.
  3. Cross-checks against the live ``CorpusStatus`` snapshot.
  4. Prints per-row status with three categories:
       OK         the referenced act is indexed
       UNKNOWN    we couldn't detect an act in the expected_answer
                  (acceptable — many rows are paraphrased)
       MISSING    the act is referenced but not indexed
  5. Exits non-zero when any row references a non-indexed act, so CI
     can fail the benchmark if a corpus regression sneaks in.

Run from the backend directory:

    python scripts/validate_benchmark.py [path/to/legal_retrieval_v1.csv]
"""

from __future__ import annotations

import asyncio
import csv
import re
import sys
from pathlib import Path

# Ensure ``app`` is importable when invoked from anywhere.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


_SECTION_REF = re.compile(
    r"\b(?:section|article|art\.|s\.)\s*(\d+[a-z]?)", re.IGNORECASE
)


async def _main(csv_path: Path) -> int:
    from app.rag.query_rewrite import detect_act_keys, detect_section_numbers
    from app.services.act_registry import ACT_REGISTRY
    from app.services.corpus_status import get_corpus_status

    status = await get_corpus_status()
    indexed = set(status.indexed_keys)
    supported = set(status.supported_keys)

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    if not rows:
        print(f"[validate] CSV is empty: {csv_path}")
        return 2

    print(f"[validate] {len(rows)} rows · {csv_path}")
    print(
        f"[validate] corpus: {len(indexed)} indexed / "
        f"{len(supported)} supported"
    )
    print()

    ok = unknown = missing = orphan = 0
    bad_rows: list[tuple[int, str, str]] = []

    for i, row in enumerate(rows, start=1):
        question = row.get("question", "").strip()
        expected = row.get("expected_answer", "").strip()
        combined = f"{question} {expected}"

        # Detect act keys from both the question and the expected_answer.
        # The expected_answer carries the canonical wording (statutory
        # body), so it's the better signal for act detection.
        detected = detect_act_keys(combined)
        sections = detect_section_numbers(combined)

        if not detected:
            status_str = "UNKNOWN"
            unknown += 1
        elif all(k in indexed for k in detected):
            status_str = "OK"
            ok += 1
        else:
            absent = [
                k for k in detected
                if k not in indexed
            ]
            if all(k in supported for k in absent):
                status_str = f"MISSING ({', '.join(absent)})"
                missing += 1
            else:
                status_str = f"ORPHAN ({', '.join(absent)})"
                orphan += 1
            bad_rows.append((i, question, status_str))

        print(
            f"  [{i:3d}] {status_str:<28}  "
            f"acts={','.join(detected) or '-':<12}  "
            f"sec={','.join(sections) or '-':<8}  "
            f"{question[:60]}"
        )

    print()
    print(
        f"[validate] summary: OK={ok}  UNKNOWN={unknown}  "
        f"MISSING={missing}  ORPHAN={orphan}"
    )
    if bad_rows:
        print()
        print("[validate] rows that need attention:")
        for i, q, s in bad_rows:
            print(f"  row {i}: {s}  —  {q[:80]}")
        print()
        # Suggest action — missing acts are ingestion issues; orphan acts
        # are registry issues. Either way, the operator needs to know.
        first_missing = sorted({
            k.replace("MISSING (", "").rstrip(")")
            for _, _, status_str in bad_rows
            for k in status_str.replace(",", " ").split()
            if status_str.startswith("MISSING")
        })
        if first_missing:
            print(
                "[validate] action: re-run corpus ingestion to bring "
                f"missing acts ({', '.join(first_missing)}) into the "
                "index."
            )
        return 1
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    default_path = (
        _BACKEND.parent / "evaluations" / "legal_retrieval_v1.csv"
    )
    path = Path(args[0]) if args else default_path
    if not path.exists():
        print(f"[validate] not found: {path}", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.new_event_loop().run_until_complete(_main(path)))
