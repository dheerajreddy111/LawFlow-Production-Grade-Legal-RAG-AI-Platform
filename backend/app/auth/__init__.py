"""Authentication and authorization.

- :mod:`app.auth.models`    SQLAlchemy User + RefreshToken tables
- :mod:`app.auth.passwords` bcrypt hashing
- :mod:`app.auth.tokens`    JWT sign/verify for access + refresh
- :mod:`app.auth.schemas`   Pydantic request/response shapes
- :mod:`app.auth.deps`      FastAPI dependencies (current_user, require_admin)
"""

from app.auth.deps import (
    current_user,
    current_user_optional,
    require_admin,
    require_role,
)
from app.auth.models import RefreshToken, User, UserRole

__all__ = [
    "RefreshToken",
    "User",
    "UserRole",
    "current_user",
    "current_user_optional",
    "require_admin",
    "require_role",
]
