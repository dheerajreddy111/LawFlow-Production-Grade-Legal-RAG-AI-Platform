"""Dump the FastAPI OpenAPI schema to a JSON file.

Used by `npm run gen:types` in the frontend to generate strongly-typed
clients without depending on a running backend. The script imports the
FastAPI app, calls `.openapi()`, writes the result to disk.

Run from the backend directory:

    python scripts/dump_openapi.py [--output openapi.json]

The output path is relative to the backend directory by default. The
frontend's `gen:types` script consumes `backend/openapi.json` and
regenerates `frontend/app/lib/admin/api.generated.ts`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the backend package is importable when invoked from anywhere.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=_BACKEND_DIR / "openapi.json",
        help="Path to write the OpenAPI schema (default: backend/openapi.json).",
    )
    args = parser.parse_args()

    # Import after argparse so --help is cheap (avoids loading the full
    # app stack just to print usage).
    from app.main import app

    schema = app.openapi()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(schema, indent=2, sort_keys=True))
    print(f"Wrote OpenAPI schema → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
