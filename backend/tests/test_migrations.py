"""Alembic upgrade/downgrade smoke tests.

These exercise the migration scripts themselves, not the runtime auth
or admin endpoints. They run against an isolated temp SQLite file so
the per-test fresh-DB conftest fixture isn't required (and would be
counterproductive — we set ``DATABASE_URL`` to a path we own).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.db.migrations import downgrade_to_base_sync, upgrade_to_head_sync

# All the tables the migration chain must produce at head. If a future
# migration drops one, fix this list — it's intentionally explicit.
_EXPECTED_TABLES: set[str] = {
    "users",
    "refresh_tokens",
    "query_events",
    "evaluation_runs",
    "jobs",
}


def _sqlite_tables(db_path: Path) -> set[str]:
    """Use stdlib sqlite3 so the assertion is independent of SQLAlchemy."""
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {r[0] for r in rows if not r[0].startswith("sqlite_")}


@pytest.fixture
def _temp_db_url(monkeypatch) -> tuple[str, Path]:
    """Per-test SQLite file. The autouse conftest fixture also runs but
    its DATABASE_URL is overwritten here for this test only."""
    tmp = Path(tempfile.mkdtemp(prefix="lawflow-mig-"))
    db_file = tmp / "mig.db"
    url = f"sqlite+aiosqlite:///{db_file}"
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        yield url, db_file
    finally:
        try:
            db_file.unlink(missing_ok=True)
            tmp.rmdir()
        except OSError:
            pass


def test_upgrade_to_head_creates_expected_tables(_temp_db_url):
    url, db_file = _temp_db_url
    assert not db_file.exists()  # virgin DB before migration

    upgrade_to_head_sync(database_url=url)

    tables = _sqlite_tables(db_file)
    # alembic_version is created as the migration bookkeeping table —
    # expected on any migrated DB, not part of the app schema.
    assert "alembic_version" in tables
    missing = _EXPECTED_TABLES - tables
    assert not missing, f"upgrade left tables uncreated: {missing}"


def test_upgrade_is_idempotent(_temp_db_url):
    """Running upgrade twice must not raise (alembic_version short-circuit)."""
    url, _ = _temp_db_url
    upgrade_to_head_sync(database_url=url)
    upgrade_to_head_sync(database_url=url)  # no-op the second time


def test_downgrade_to_base_drops_all_app_tables(_temp_db_url):
    url, db_file = _temp_db_url
    upgrade_to_head_sync(database_url=url)
    # Sanity: tables exist after upgrade.
    assert _EXPECTED_TABLES <= _sqlite_tables(db_file)

    downgrade_to_base_sync(database_url=url)
    after = _sqlite_tables(db_file)

    # All app tables gone. alembic_version remains (it's bookkeeping).
    remaining_app_tables = after & _EXPECTED_TABLES
    assert remaining_app_tables == set(), (
        f"downgrade left app tables behind: {remaining_app_tables}"
    )


def test_env_url_overrides_ini(_temp_db_url):
    """env.py prefers ``DATABASE_URL`` over the .ini value. The runner
    sets it explicitly; this test asserts that override actually
    takes effect by checking the migration created the file at the
    env path, not at the .ini default."""
    url, db_file = _temp_db_url
    upgrade_to_head_sync(database_url=url)
    assert db_file.exists()
    assert os.environ["DATABASE_URL"] == url
