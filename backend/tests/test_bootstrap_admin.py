"""Bootstrap admin provisioning tests.

Exercises ``app.auth.bootstrap.ensure_bootstrap_admin`` end-to-end
against a fresh SQLite per test (provided by the conftest fixture).
The helper is invoked directly — these tests deliberately avoid
``TestClient`` so the lifespan side-effects don't muddy assertions
about a single bootstrap invocation.

``settings.bootstrap_admin_*`` are read at the singleton's
construction time, so tests monkeypatch the attribute rather than
the env var.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.auth.bootstrap import ensure_bootstrap_admin
from app.auth.models import User, UserRole
from app.auth.passwords import hash_password, verify_password
from app.config import settings
from app.db.session import create_all, session_scope


def _run(coro):
    """Run an awaitable on a fresh loop so we don't fight pytest-asyncio."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _all_users() -> list[User]:
    async with session_scope() as s:
        result = await s.execute(select(User))
        return list(result.scalars().all())


async def _user_for(email: str) -> User | None:
    async with session_scope() as s:
        result = await s.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()


# ── Required test cases ─────────────────────────────────────────────────────


def test_bootstrap_creates_admin_when_absent(monkeypatch):
    """No admin in DB + env vars set → admin is created."""
    monkeypatch.setattr(settings, "bootstrap_admin_email", "ops@example.com")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "verystrongpwd123")

    async def run() -> None:
        await create_all()
        result = await ensure_bootstrap_admin()
        assert result == "created"

        user = await _user_for("ops@example.com")
        assert user is not None
        assert user.role == UserRole.ADMIN.value
        assert user.is_active is True

    _run(run())


def test_bootstrap_is_idempotent(monkeypatch):
    """Second invocation must be a no-op — no duplicate rows, no mutation."""
    monkeypatch.setattr(settings, "bootstrap_admin_email", "ops@example.com")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "verystrongpwd123")

    async def run() -> None:
        await create_all()
        first = await ensure_bootstrap_admin()
        assert first == "created"

        # Capture the persisted hash so we can assert it doesn't change.
        before = await _user_for("ops@example.com")
        assert before is not None
        original_hash = before.password_hash

        second = await ensure_bootstrap_admin()
        assert second == "exists"
        third = await ensure_bootstrap_admin()
        assert third == "exists"

        users = await _all_users()
        assert len(users) == 1
        assert users[0].password_hash == original_hash

    _run(run())


def test_bootstrap_password_is_hashed_not_stored_plaintext(monkeypatch):
    """Password must traverse the same hashing path as normal signups.

    Verifies the stored value is bcrypt-formatted, isn't the plaintext,
    and ``verify_password`` (the same fn login uses) accepts the
    original value.
    """
    plaintext = "another-very-strong-pwd!"
    monkeypatch.setattr(settings, "bootstrap_admin_email", "ops@example.com")
    monkeypatch.setattr(settings, "bootstrap_admin_password", plaintext)

    async def run() -> None:
        await create_all()
        await ensure_bootstrap_admin()
        user = await _user_for("ops@example.com")
        assert user is not None

        # The plaintext must never appear verbatim.
        assert plaintext not in user.password_hash
        # bcrypt hashes start with $2 (one of $2a$, $2b$, $2y$).
        assert user.password_hash.startswith("$2")
        # The verify path used by /auth/login accepts it.
        assert verify_password(plaintext, user.password_hash) is True
        assert verify_password("wrong-password", user.password_hash) is False

    _run(run())


def test_bootstrap_skipped_when_env_vars_missing(monkeypatch):
    """Both env vars absent → no admin created, return value reflects skip."""
    monkeypatch.setattr(settings, "bootstrap_admin_email", None)
    monkeypatch.setattr(settings, "bootstrap_admin_password", None)

    async def run() -> None:
        await create_all()
        result = await ensure_bootstrap_admin()
        assert result == "skipped"
        assert await _all_users() == []

    _run(run())


def test_bootstrap_skipped_when_only_email_set(monkeypatch):
    """Either var missing → still skip. The pair must be all-or-nothing."""
    monkeypatch.setattr(settings, "bootstrap_admin_email", "ops@example.com")
    monkeypatch.setattr(settings, "bootstrap_admin_password", None)

    async def run() -> None:
        await create_all()
        result = await ensure_bootstrap_admin()
        assert result == "skipped"
        assert await _all_users() == []

    _run(run())


def test_bootstrap_refuses_to_mutate_existing_non_admin(monkeypatch):
    """If the bootstrap email is already held by a non-admin user, refuse to
    promote — the spec is explicit about never mutating existing users.
    """
    monkeypatch.setattr(settings, "bootstrap_admin_email", "alice@example.com")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "bootstrap-pwd-x")

    async def run() -> None:
        await create_all()
        original_hash = hash_password("alice-own-password")
        async with session_scope() as s:
            s.add(
                User(
                    email="alice@example.com",
                    password_hash=original_hash,
                    role=UserRole.USER.value,
                    is_active=True,
                    full_name="Alice",
                )
            )
            await s.commit()

        result = await ensure_bootstrap_admin()
        assert result == "blocked"

        # Existing user is byte-identical: role, password, name all preserved.
        user = await _user_for("alice@example.com")
        assert user is not None
        assert user.role == UserRole.USER.value
        assert user.full_name == "Alice"
        assert user.password_hash == original_hash
        assert verify_password("alice-own-password", user.password_hash) is True
        # The bootstrap password definitely did not overwrite anything.
        assert verify_password("bootstrap-pwd-x", user.password_hash) is False

    _run(run())
