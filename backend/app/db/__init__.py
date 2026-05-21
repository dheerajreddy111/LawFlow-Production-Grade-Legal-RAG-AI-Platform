"""SQLAlchemy async DB layer.

Importing :mod:`app.db` is side-effect free — the engine is constructed
lazily on first use so importing the module during tooling (e.g. mypy,
test collection) does not require a database URL to be present.
"""

from app.db.base import Base
from app.db.session import (
    create_all,
    dispose_engine,
    get_engine,
    get_session,
    session_scope,
)

__all__ = [
    "Base",
    "create_all",
    "dispose_engine",
    "get_engine",
    "get_session",
    "session_scope",
]
