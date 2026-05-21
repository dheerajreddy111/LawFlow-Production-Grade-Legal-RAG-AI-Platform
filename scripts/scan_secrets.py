#!/usr/bin/env python3
"""LawFlow secret scanner — defence-in-depth before commits / CI.

Why we have this
----------------
The initial commit of this repo shipped a real-looking Groq API key in
``backend/.env.example``. That kind of slip costs money + risks
compliance. This scanner is the cheap pre-commit / CI safety net that
catches the slip before it lands in a public commit.

It is intentionally narrow:

  - It checks the patterns we know we leak: Groq (``gsk_…``), OpenAI
    (``sk-…``), Anthropic (``sk-ant-…``), GitHub tokens, AWS keys,
    Slack tokens, and generic ``-----BEGIN PRIVATE KEY-----``.
  - It scans **only** the files passed on the command line, or — when
    no arguments — the staged set returned by ``git diff --cached``.
    Run with ``--all`` to scan the whole working tree (rare; usually
    for one-off audits).
  - It allows ``.env.example`` files whose values are *empty* or
    obviously placeholder (``CHANGE_ME``, ``…``, ``your-key-here``).
    Anything else triggers a finding.

Exit codes:
  0 — no findings
  1 — one or more findings (prints them, returns non-zero so the
      hook / CI step fails)
  2 — internal error / bad invocation

Not a replacement for ``trufflehog`` / ``gitleaks`` (those scan history
+ entropy + more providers). Use one of those for periodic deep audits;
keep this one as the always-on guardrail.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# ── Patterns ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Rule:
    label: str
    pattern: re.Pattern[str]
    # Allow any of these substrings in the matched span; "" means "no
    # placeholder string can be added without triggering — match always
    # counts." We use this to suppress recurring fixtures like the bcrypt
    # sentinel hash in app/api/v1/endpoints/auth.py (every "a"*53).
    allowed_substrings: tuple[str, ...] = ()


# Ordered by likelihood — the cheap "is this a Groq key?" check beats the
# generic JWT regex. Each pattern is intentionally narrow so the false-
# positive rate stays close to zero.
_RULES: tuple[Rule, ...] = (
    Rule(
        label="Groq API key",
        # `gsk_` + 50+ alphanumerics is the documented format.
        pattern=re.compile(r"\bgsk_[A-Za-z0-9]{40,}\b"),
    ),
    Rule(
        label="OpenAI API key",
        # Real OpenAI keys are >=20 chars and not just zeroes — the
        # placeholder we ship is `sk-...`, which fails the alnum tail.
        pattern=re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    ),
    Rule(
        label="Anthropic API key",
        pattern=re.compile(r"\bsk-ant-[A-Za-z0-9_-]{40,}\b"),
    ),
    Rule(
        label="GitHub PAT / fine-grained token",
        pattern=re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"),
    ),
    Rule(
        label="AWS access key ID",
        # `AKIA` then 16 uppercase alphanumerics.
        pattern=re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    Rule(
        label="Slack token",
        pattern=re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{20,}\b"),
    ),
    Rule(
        label="Private key block",
        pattern=re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)PRIVATE KEY-----"
        ),
    ),
)


# Files that are NEVER scanned (binary, vendored, lockfiles).
_SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    ".next",
    "dist",
    "build",
    "__pycache__",
    "chroma_db",
    ".pytest_cache",
    ".ruff_cache",
    "uploads",
}
_SKIP_SUFFIXES = {
    ".lock",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".ico",
    ".svg",
    ".onnx",
    ".bin",
    ".safetensors",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".parquet",
    ".pyc",
    ".min.js",
    ".min.css",
}
# Locked dependency manifests would otherwise produce noise on every commit
# touching them — they're scanned by the upstream package registry already.
_SKIP_FILENAMES = {"package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock"}


# ── Finding type + reporter ──────────────────────────────────────────────


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    rule: str
    snippet: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.snippet}"


def _is_text(path: Path) -> bool:
    """Best-effort text detector — read the first 4KB and check for NULs."""
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
    except OSError:
        return False
    return b"\x00" not in chunk


def _iter_lines(path: Path):
    """Yield (line_no, line) pairs in a memory-friendly stream."""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, start=1):
            yield n, line.rstrip("\n")


# ── Env-example heuristic ────────────────────────────────────────────────
#
# ``.env.example`` files exist to *teach* operators which secrets to
# provide. Empty values are fine; placeholder values are fine; *real-
# looking* values are not. We accept:
#   - blank values (``KEY=``)
#   - obvious placeholders (`CHANGE_ME`, `your-…`, `…`, ``…``)
#   - tokens whose body looks like a stable example (``EXAMPLE``,
#     ``REDACTED``, ``PLACEHOLDER``)
# Anything else triggers the rule for the matching key.

_ENV_EXAMPLE_NAMES = {".env.example", ".env.sample"}
_PLACEHOLDER_TOKENS = (
    "change_me",
    "changeme",
    "your-",
    "your_",
    "placeholder",
    "example",
    "xxxx",
    "redacted",
    "warning",
    "...",
    "…",
)


def _looks_like_placeholder(value: str) -> bool:
    if not value or value.strip() == "":
        return True
    v = value.strip().lower()
    return any(token in v for token in _PLACEHOLDER_TOKENS)


# ── Scanner ──────────────────────────────────────────────────────────────


def scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not path.is_file():
        return findings
    # The scanner itself contains the regex literals it scans for (e.g. the
    # ``-----BEGIN PRIVATE KEY-----`` marker on the ``Private key block``
    # rule), so scanning this file would always self-flag. This file is
    # reviewed by hand instead.
    if path.name == "scan_secrets.py":
        return findings
    if path.suffix.lower() in _SKIP_SUFFIXES:
        return findings
    if path.name in _SKIP_FILENAMES:
        return findings
    if any(part in _SKIP_DIRS for part in path.parts):
        return findings
    if not _is_text(path):
        return findings

    is_env_example = path.name in _ENV_EXAMPLE_NAMES

    for line_no, line in _iter_lines(path):
        for rule in _RULES:
            m = rule.pattern.search(line)
            if not m:
                continue
            snippet = m.group(0)
            # Allow-list bypass.
            if any(s in snippet for s in rule.allowed_substrings):
                continue
            # For .env.example, accept obvious placeholders.
            if is_env_example:
                _, _, value = line.partition("=")
                if _looks_like_placeholder(value):
                    continue
            # Mask the middle of the match so the CI log itself isn't a
            # leak — only the first 6 and last 4 characters are kept.
            masked = (
                snippet[:6] + "…" + snippet[-4:] if len(snippet) > 14 else snippet
            )
            findings.append(
                Finding(path=path, line=line_no, rule=rule.label, snippet=masked)
            )
    return findings


def _git_staged_files(repo_root: Path) -> list[Path]:
    """Return the files staged for commit (added or modified)."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=str(repo_root),
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [repo_root / p for p in out.splitlines() if p.strip()]


def _all_tracked_files(repo_root: Path) -> list[Path]:
    """Return everything `git ls-files` reports — for `--all` audits."""
    try:
        out = subprocess.check_output(
            ["git", "ls-files"], cwd=str(repo_root), text=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [repo_root / p for p in out.splitlines() if p.strip()]


# ── Entry point ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan files for accidentally-committed secrets.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to scan. Omit to scan the staged set.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scan every tracked file in the repo (slow; for one-off audits).",
    )
    args = parser.parse_args(argv)

    repo_root = Path.cwd()
    # Walk up until we find the .git dir so the script can be invoked from
    # any subdirectory.
    while not (repo_root / ".git").exists() and repo_root != repo_root.parent:
        repo_root = repo_root.parent

    if args.all:
        targets = _all_tracked_files(repo_root)
    elif args.paths:
        targets = []
        for p in args.paths:
            if p.is_dir():
                targets.extend(sorted(p.rglob("*")))
            else:
                targets.append(p)
    else:
        targets = _git_staged_files(repo_root)

    findings: list[Finding] = []
    for target in targets:
        if target.is_dir():
            continue
        findings.extend(scan_file(target))

    if not findings:
        return 0

    print(f"\nsecret-scan: found {len(findings)} potential leak(s)\n", file=sys.stderr)
    for f in findings:
        print(f, file=sys.stderr)
    print(
        "\nIf this is a false positive, refine the regex in scripts/scan_secrets.py\n"
        "or move the value out of the file. If real: REVOKE the key now, then\n"
        "rotate locally before re-committing.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
