"""Password hashing.

Uses passlib's bcrypt backend with a fixed scheme. We expose two functions
only — ``hash_password`` and ``verify_password`` — so callers never touch
the bcrypt API directly.
"""

from __future__ import annotations

from passlib.context import CryptContext

# bcrypt has a 72-byte input limit; passlib's bcrypt context truncates
# silently if we don't pre-hash. We surface that as a length validation
# error at the schema layer (see app.auth.schemas) so the policy is visible.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_context.verify(plain, hashed)
    except ValueError:
        # Malformed hash on disk → treat as auth failure, not a 500.
        return False
