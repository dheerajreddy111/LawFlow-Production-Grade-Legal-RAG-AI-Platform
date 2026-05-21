"""Pydantic request/response schemas for the auth API.

Kept separate from the SQLAlchemy models so the wire contract evolves
independently of the storage layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.auth.models import UserRole

# bcrypt has a 72-byte truncation limit. Cap the password length explicitly
# at the schema layer so the policy is visible to API consumers.
_MAX_PASSWORD = 72


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=_MAX_PASSWORD)
    full_name: str | None = Field(default=None, max_length=200)

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        # Minimal sanity check — we do not enforce mixed case / symbols here
        # to keep UX usable; deployers can tighten via a frontend policy.
        if v.strip() != v:
            raise ValueError("Password must not have leading/trailing whitespace")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=_MAX_PASSWORD)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds until access token expiry


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None = None
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    """Returned by login / signup / refresh — pairs access token with profile."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


class MessageResponse(BaseModel):
    detail: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=_MAX_PASSWORD)
    new_password: str = Field(min_length=8, max_length=_MAX_PASSWORD)

    @field_validator("new_password")
    @classmethod
    def _new_password_strength(cls, v: str) -> str:
        if v.strip() != v:
            raise ValueError("Password must not have leading/trailing whitespace")
        return v
