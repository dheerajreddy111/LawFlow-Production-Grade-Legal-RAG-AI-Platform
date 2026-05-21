"""Alembic environment.

- Reads the DB URL from :data:`app.config.settings.database_url` so the
  runtime and migrations share a single source of truth.
- Supports both online (live DB) and offline (SQL script) modes.
- Online mode uses SQLAlchemy's async engine but bridges to Alembic's
  synchronous migration runner via ``connection.run_sync``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ensure ``app`` is importable when alembic is invoked from the backend/
# directory (the same prepend_sys_path the .ini sets, made explicit
# here for robustness against alternate invocations).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Importing models registers their tables on Base.metadata. Keep these
# imports here (not at module top) so the order is explicit.
from app.analytics import models as _analytics_models  # noqa: E402, F401
from app.auth import models as _auth_models  # noqa: E402, F401
from app.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.evaluation import models as _evaluation_models  # noqa: E402, F401
from app.jobs import models as _job_models  # noqa: E402, F401

config = context.config

# Inject the runtime DB URL into the Alembic config so existing logging
# config and the engine factory both see the same value.
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _include_object(object_, name, type_, reflected, compare_to) -> bool:  # noqa: ANN001
    """Skip alembic_version itself when comparing for autogenerate."""
    if type_ == "table" and name == "alembic_version":
        return False
    return True


def _is_sqlite(url_or_dialect: str) -> bool:
    """Return True when the active engine is SQLite.

    Alembic's batch-ALTER dance is only needed on SQLite (ALTER TABLE is
    severely restricted there); Postgres handles plain ALTERs natively.
    Toggling this off on Postgres keeps the generated migrations clean
    (no useless ``with batch_alter_table`` wrappers).
    """
    return url_or_dialect.startswith("sqlite")


def run_migrations_offline() -> None:
    """Generate a SQL script without connecting to a DB."""
    url = config.get_main_option("sqlalchemy.url") or ""
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
        # Auto-disable on Postgres so generated migrations don't ship
        # SQLite-only batch wrappers.
        render_as_batch=_is_sqlite(url),
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live DB through an async engine."""
    cfg_section = config.get_section(config.config_ini_section) or {}
    # Allow ``DATABASE_URL`` env var to win — keeps alembic CLI invocations
    # consistent with the runtime even when the .env is loaded later.
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        cfg_section["sqlalchemy.url"] = env_url

    connectable = async_engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
