"""Async engine and session management.

Single global engine, lazily constructed from ``settings.database_url`` on
first use. Tests can override the URL by setting ``DATABASE_URL`` before
the first call (or by calling :func:`dispose_engine` after mutating
``settings.database_url`` directly).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.db.base import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        url = settings.database_url
        # SQLite needs check_same_thread=False under the async driver; other
        # dialects ignore the kwarg.
        connect_args: dict[str, object] = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_async_engine(
            url,
            echo=False,
            future=True,
            connect_args=connect_args,
        )
        _sessionmaker = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    """Tear down the engine. Tests call this between DB URL swaps."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def create_all() -> None:
    """Create every table declared on :class:`Base`. Idempotent.

    Production startup uses Alembic instead (see ``app.db.migrations``).
    This helper survives for tests that want a faster path than running
    a full migration on every fresh DB.
    """
    # Import models so their tables register on Base.metadata before
    # create_all runs. Keep these imports local — at module level they
    # would cycle (each model module imports db.base).
    from app.analytics import models as _analytics_models  # noqa: F401
    from app.auth import models as _auth_models  # noqa: F401
    from app.evaluation import models as _evaluation_models  # noqa: F401
    from app.jobs import models as _job_models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an :class:`AsyncSession`."""
    sm = _get_sessionmaker()
    async with sm() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Standalone context manager for non-request code paths (startup, CLI)."""
    sm = _get_sessionmaker()
    async with sm() as session:
        yield session
