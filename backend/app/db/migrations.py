"""Programmatic Alembic runner.

Lets ``app.main.lifespan`` invoke ``alembic upgrade head`` without
shelling out, and tests drive ``upgrade head`` / ``downgrade base``
against an isolated DB. The shell ``alembic`` CLI is still supported
— both paths share the same ``alembic.ini`` + ``migrations/env.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)

# backend/ — the parent of app/ — is the home for alembic.ini.
_BACKEND_DIR: Path = Path(__file__).resolve().parents[2]
_ALEMBIC_INI: Path = _BACKEND_DIR / "alembic.ini"


def _make_config(database_url: str | None = None) -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    if database_url is not None:
        cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def upgrade_to_head_sync(database_url: str | None = None) -> None:
    """Run ``alembic upgrade head`` synchronously.

    ``database_url`` overrides the URL Alembic reads from settings —
    useful in tests that point at an isolated SQLite file.
    """
    cfg = _make_config(database_url)
    # When a URL was passed explicitly, the env.py honours os.environ
    # over the .ini value; mirror it here to keep the two paths
    # consistent for tests that don't bother setting env vars.
    if database_url is not None:
        old_env = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = database_url
        try:
            command.upgrade(cfg, "head")
        finally:
            if old_env is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old_env
    else:
        command.upgrade(cfg, "head")


def downgrade_to_base_sync(database_url: str | None = None) -> None:
    """Run ``alembic downgrade base`` synchronously."""
    cfg = _make_config(database_url)
    if database_url is not None:
        old_env = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = database_url
        try:
            command.downgrade(cfg, "base")
        finally:
            if old_env is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = old_env
    else:
        command.downgrade(cfg, "base")


async def upgrade_to_head() -> None:
    """Async wrapper used by FastAPI's startup lifespan.

    Alembic's command API is synchronous (and spins up its own engine
    inside env.py), so we offload to a worker thread to avoid blocking
    the event loop.
    """
    logger.info("Running alembic upgrade head")
    await asyncio.to_thread(upgrade_to_head_sync)
    logger.info("Alembic upgrade complete")
