"""Authentication endpoints.

- ``POST /auth/signup``       create a normal user
- ``POST /auth/login``        login (any active user)
- ``POST /auth/admin-login``  login restricted to admin role
- ``POST /auth/refresh``      exchange refresh-cookie for a new access token
- ``POST /auth/logout``       revoke the current refresh token + clear cookie
- ``GET  /auth/me``           current user profile

Refresh tokens travel in an httpOnly cookie (``lf_refresh``). Access
tokens are returned as JSON and the frontend stores them in memory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import current_user, lookup_user_by_email
from app.auth.models import RefreshToken, User, UserRole
from app.auth.passwords import hash_password, verify_password
from app.auth.schemas import (
    AuthResponse,
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    SignupRequest,
    UserOut,
)
from app.auth.tokens import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_refresh_token,
)
from app.config import settings
from app.db.session import get_session

router = APIRouter()

REFRESH_COOKIE_NAME = "lf_refresh"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,  # type: ignore[arg-type]
        domain=settings.cookie_domain,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/v1/auth",
        domain=settings.cookie_domain,
    )


async def _issue_tokens(
    *,
    user: User,
    session: AsyncSession,
    response: Response,
) -> AuthResponse:
    access = create_access_token(user_id=user.id, role=user.role)
    raw_refresh, jti, exp = create_refresh_token(user_id=user.id)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(raw_refresh),
            jti=jti,
            expires_at=exp,
        )
    )
    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(user)

    _set_refresh_cookie(response, raw_refresh)
    return AuthResponse(
        access_token=access,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def signup(
    body: SignupRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthResponse:
    email = body.email.lower()
    existing = await lookup_user_by_email(session, email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists",
        )
    user = User(
        email=email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        role=UserRole.USER.value,
        is_active=True,
    )
    session.add(user)
    await session.flush()  # populate user.id
    return await _issue_tokens(user=user, session=session, response=response)


async def _authenticate(
    session: AsyncSession, *, email: str, password: str
) -> User:
    user = await lookup_user_by_email(session, email.lower())
    # Constant-time-ish: always run a hash compare so we don't leak whether
    # the email exists. verify_password on a sentinel hash is cheap enough.
    sentinel = "$2b$12$" + "a" * 53  # well-formed but never-matches bcrypt hash
    if user is None:
        verify_password(password, sentinel)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )
    if not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return user


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Login with email + password (any role)",
)
async def login(
    body: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthResponse:
    user = await _authenticate(session, email=body.email, password=body.password)
    return await _issue_tokens(user=user, session=session, response=response)


@router.post(
    "/admin-login",
    response_model=AuthResponse,
    summary="Login restricted to admin accounts",
)
async def admin_login(
    body: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthResponse:
    user = await _authenticate(session, email=body.email, password=body.password)
    if user.role != UserRole.ADMIN.value:
        # Same opaque message as bad creds — don't leak which accounts are admins.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    return await _issue_tokens(user=user, session=session, response=response)


@router.post(
    "/refresh",
    response_model=AuthResponse,
    summary="Exchange refresh cookie for a new access token (rotates refresh)",
)
async def refresh(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    lf_refresh: Annotated[str | None, Cookie()] = None,
) -> AuthResponse:
    if not lf_refresh:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token",
        )
    try:
        claims = decode_refresh_token(lf_refresh)
    except TokenError as exc:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    token_hash = hash_refresh_token(lf_refresh)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None or not row.is_active:
        # Possible token reuse after rotation — revoke all refresh tokens for
        # this user as a defence-in-depth measure.
        if row is not None:
            await _revoke_all_for_user(session, row.user_id)
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked or expired",
        )

    user = await session.get(User, int(claims.sub))
    if user is None or not user.is_active:
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Rotate: revoke the presented refresh token, issue a fresh pair.
    row.revoked_at = datetime.now(timezone.utc)
    return await _issue_tokens(user=user, session=session, response=response)


async def _revoke_all_for_user(session: AsyncSession, user_id: int) -> None:
    stmt = select(RefreshToken).where(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    )
    result = await session.execute(stmt)
    now = datetime.now(timezone.utc)
    for row in result.scalars():
        row.revoked_at = now
    await session.commit()


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Revoke the current refresh token and clear the cookie",
)
async def logout(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    lf_refresh: Annotated[str | None, Cookie()] = None,
) -> MessageResponse:
    if lf_refresh:
        token_hash = hash_refresh_token(lf_refresh)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            await session.commit()
    _clear_refresh_cookie(response)
    return MessageResponse(detail="Logged out")


@router.get(
    "/me",
    response_model=UserOut,
    summary="Current authenticated user",
)
async def me(user: Annotated[User, Depends(current_user)]) -> UserOut:
    return UserOut.model_validate(user)


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change the current user's password (requires current password)",
)
async def change_password(
    body: ChangePasswordRequest,
    response: Response,
    user: Annotated[User, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MessageResponse:
    """Change the authenticated user's password.

    Requires the current password as proof-of-possession. On success
    every active refresh token is revoked (the user is forced to log
    in again on other devices) and the current refresh cookie is
    cleared. The access token survives until expiry — fixing that
    requires a JWT denylist, which is intentionally out-of-scope.
    """
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current password",
        )
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    user.password_hash = hash_password(body.new_password)
    await _revoke_all_for_user(session, user.id)
    # _revoke_all_for_user commits — refresh the user so subsequent reads
    # don't hit a stale row.
    await session.refresh(user)
    _clear_refresh_cookie(response)
    return MessageResponse(detail="Password updated")
