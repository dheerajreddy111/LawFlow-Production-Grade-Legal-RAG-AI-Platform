"""FastAPI dependencies for authentication and RBAC.

Three building blocks:

- :func:`current_user`          required-auth: 401 if no/invalid token
- :func:`current_user_optional` permissive: returns None when no token
- :func:`require_role`/:func:`require_admin` role-gated variants

The token is read from the ``Authorization: Bearer <jwt>`` header. The
refresh-token cookie is *never* accepted as an access credential — that
path is the dedicated ``/auth/refresh`` endpoint.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.auth.tokens import TokenError, decode_access_token
from app.db.session import get_session


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def _resolve_user(
    token: str,
    session: AsyncSession,
) -> User:
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = await session.get(User, int(claims.sub))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Defensive: if a role was changed mid-session, the token still names
    # the old role. The DB is the source of truth — overwrite the claim.
    if user.role != claims.role:
        # No exception: stale role just means downgrade/upgrade applies on
        # the *next* call. We trust the DB row for the current request.
        pass
    return user


async def current_user(
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = ...,  # type: ignore[assignment]
) -> User:
    token = _extract_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _resolve_user(token, session)


async def current_user_optional(
    authorization: Annotated[str | None, Header()] = None,
    session: Annotated[AsyncSession, Depends(get_session)] = ...,  # type: ignore[assignment]
) -> User | None:
    token = _extract_bearer(authorization)
    if not token:
        return None
    try:
        return await _resolve_user(token, session)
    except HTTPException:
        return None


def require_role(*allowed: UserRole | str):
    """Dependency factory: ensure the current user has one of these roles."""
    allowed_values = {r.value if isinstance(r, UserRole) else str(r) for r in allowed}

    async def _dep(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient privileges",
            )
        return user

    return _dep


# Common alias for the most-used guard.
require_admin = require_role(UserRole.ADMIN)


async def lookup_user_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email.lower())
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
