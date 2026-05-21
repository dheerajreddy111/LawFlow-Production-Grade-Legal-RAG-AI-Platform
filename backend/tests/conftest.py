"""Pytest fixtures shared across the LawFlow regression tests.

The integration suite verifies the LangChain/LangGraph layer does not
regress the existing API contract (response shape, SSE event sequence,
memory behaviour) — and that the opt-in LangGraph path is duck-compatible
with the native :class:`RAGEngine`.

Real LLM/Groq calls are gated behind ``GROQ_API_KEY`` in the env; tests
that need them are marked and skipped automatically when the key is
absent (so CI without secrets still passes).
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Awaitable, Iterator, TypeVar

import pytest

_T = TypeVar("_T")


def _run_in_thread(coro: Awaitable[_T]) -> _T:
    """Run an awaitable in a *fresh* event loop on a worker thread.

    Test functions decorated with ``asyncio_mode=auto`` already own a loop;
    we cannot ``run_until_complete`` on a new loop from inside them, but we
    can offload to another thread which has its own loop. This is only used
    by setup helpers — not by application code.
    """
    box: dict[str, object] = {}

    def runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            box["result"] = loop.run_until_complete(coro)
        except BaseException as exc:  # noqa: BLE001 — re-raise on the caller
            box["exc"] = exc
        finally:
            loop.close()

    t = threading.Thread(target=runner)
    t.start()
    t.join()
    if "exc" in box:
        raise box["exc"]  # type: ignore[misc]
    return box["result"]  # type: ignore[return-value]


# ── Per-test SQLite DB ──────────────────────────────────────────────────────
# Every test that boots a TestClient triggers the FastAPI lifespan, which
# runs auth-table creation. We point each test at a fresh SQLite file so
# users/refresh-tokens never leak across tests.
#
# We also explicitly null out BOOTSTRAP_ADMIN_* on every test. Without this
# the developer's local backend/.env can introduce a bootstrap admin row
# into every fresh test DB via the lifespan, perturbing user-count
# assertions in test_admin / test_auth. Tests that need a bootstrap admin
# (test_bootstrap_admin.py) monkeypatch the fields explicitly.


@pytest.fixture(autouse=True)
def _fresh_auth_db() -> Iterator[Path]:
    tmp = Path(tempfile.mkdtemp(prefix="lawflow-test-"))
    db_path = tmp / "auth.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    old_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url

    from app.config import settings as _settings
    from app.db import session as _db_session

    old_url = _settings.database_url
    _settings.database_url = url

    # Quarantine any local .env BOOTSTRAP_ADMIN_* settings so the lifespan
    # doesn't seed an admin into a fresh test DB.
    old_bootstrap_email = _settings.bootstrap_admin_email
    old_bootstrap_password = _settings.bootstrap_admin_password
    _settings.bootstrap_admin_email = None
    _settings.bootstrap_admin_password = None

    _run_in_thread(_db_session.dispose_engine())

    try:
        yield db_path
    finally:
        _settings.database_url = old_url
        _settings.bootstrap_admin_email = old_bootstrap_email
        _settings.bootstrap_admin_password = old_bootstrap_password
        if old_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_env
        _run_in_thread(_db_session.dispose_engine())
        try:
            db_path.unlink(missing_ok=True)
            tmp.rmdir()
        except OSError:
            pass


# ── Auth helpers for tests that hit protected endpoints ─────────────────────


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def signup_user(
    client,
    *,
    email: str = "user@example.com",
    password: str = "supersecret123",
    full_name: str | None = "Test User",
) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert r.status_code == 201, r.text
    return _bearer(r.json()["access_token"])


def _promote_to_admin_sync(email: str) -> None:
    """Promote a user to admin via direct SQLite UPDATE.

    Avoids spinning up the async engine inside an async test (which already
    owns its event loop). The conftest forces SQLite for tests, so a stdlib
    sqlite3 connection is sufficient.
    """
    db_url = os.environ.get("DATABASE_URL", "")
    prefix = "sqlite+aiosqlite:///"
    assert db_url.startswith(prefix), f"unexpected DB url: {db_url!r}"
    db_file = db_url[len(prefix):]
    with sqlite3.connect(db_file) as conn:
        cur = conn.execute(
            "UPDATE users SET role = 'admin' WHERE email = ?", (email.lower(),)
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"User {email!r} not found for promotion")
        conn.commit()


def signup_admin(
    client,
    *,
    email: str = "admin@example.com",
    password: str = "supersecret123",
) -> dict[str, str]:
    """Sign up, promote to admin (direct SQLite), then admin-login.

    Returns Bearer headers ready for use with ``client.get/post(...)``.
    """
    r = client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "full_name": "Admin"},
    )
    assert r.status_code == 201, r.text

    _promote_to_admin_sync(email)

    r = client.post(
        "/api/v1/auth/admin-login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200, r.text
    return _bearer(r.json()["access_token"])


# ── Existing LLM marker (kept) ───────────────────────────────────────────────


def _has_groq() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))


def _has_anthropic() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


needs_llm = pytest.mark.skipif(
    not (_has_groq() or _has_anthropic()),
    reason="No LLM API key configured — skipping LLM-dependent tests",
)
