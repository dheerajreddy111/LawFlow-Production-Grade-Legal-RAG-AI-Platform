"""JWT sign/verify for access and refresh tokens.

- Access tokens are short-lived (~30 min), carry user id + role, are
  validated stateless on every request.
- Refresh tokens are long-lived (~14 days), have a ``jti`` we also persist
  hashed in the ``refresh_tokens`` table so they can be revoked.

Both tokens share a single HMAC secret (``settings.jwt_secret_key``).
Algorithm defaults to HS256.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt

from app.config import settings

TokenType = Literal["access", "refresh"]


@dataclass(frozen=True)
class AccessClaims:
    sub: str          # user id (stringified)
    role: str
    jti: str
    exp: datetime
    iat: datetime
    type: TokenType


@dataclass(frozen=True)
class RefreshClaims:
    sub: str
    jti: str
    exp: datetime
    iat: datetime
    type: TokenType


class TokenError(Exception):
    """Token failed verification (bad signature, expired, wrong type)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode(payload: dict) -> str:
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def _decode(token: str) -> dict:
    try:
        return jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Invalid token") from exc


def create_access_token(*, user_id: int, role: str) -> str:
    now = _now()
    exp = now + timedelta(minutes=settings.access_token_expire_minutes)
    return _encode(
        {
            "sub": str(user_id),
            "role": role,
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "type": "access",
        }
    )


def create_refresh_token(*, user_id: int) -> tuple[str, str, datetime]:
    """Return (raw_token, jti, expires_at). Persist the sha256 of raw_token."""
    now = _now()
    exp = now + timedelta(days=settings.refresh_token_expire_days)
    jti = uuid.uuid4().hex
    token = _encode(
        {
            "sub": str(user_id),
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "type": "refresh",
            # A bit of extra entropy so two refreshes within the same second
            # cannot collide even if jti generation is mocked.
            "nonce": secrets.token_urlsafe(8),
        }
    )
    return token, jti, exp


def decode_access_token(token: str) -> AccessClaims:
    payload = _decode(token)
    if payload.get("type") != "access":
        raise TokenError("Wrong token type")
    return AccessClaims(
        sub=str(payload["sub"]),
        role=str(payload.get("role", "user")),
        jti=str(payload.get("jti", "")),
        iat=datetime.fromtimestamp(int(payload["iat"]), tz=timezone.utc),
        exp=datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc),
        type="access",
    )


def decode_refresh_token(token: str) -> RefreshClaims:
    payload = _decode(token)
    if payload.get("type") != "refresh":
        raise TokenError("Wrong token type")
    return RefreshClaims(
        sub=str(payload["sub"]),
        jti=str(payload["jti"]),
        iat=datetime.fromtimestamp(int(payload["iat"]), tz=timezone.utc),
        exp=datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc),
        type="refresh",
    )


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
