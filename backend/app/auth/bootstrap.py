"""Bootstrap admin provisioning.

Idempotent startup helper. When ``BOOTSTRAP_ADMIN_EMAIL`` and
``BOOTSTRAP_ADMIN_PASSWORD`` are both set, ensures an admin row exists
for that email — creating it on first boot and short-circuiting on
every subsequent boot.

Operational guarantees (enforced by this module and its tests):

* Idempotent: repeated invocations are no-ops once the admin exists.
* Never mutates an existing user. If the bootstrap email is already
  held by a non-admin, we log a warning and skip — operators must
  resolve the collision manually (use a different email, or promote
  via a one-off DB session).
* Never resets passwords. ``BOOTSTRAP_ADMIN_PASSWORD`` is only ever
  read at creation time. Rotation happens through normal channels.
* Uses the same ``hash_password`` path as signup, so the resulting
  row is indistinguishable from a regular user except for ``role``.
* Never logs the plaintext password. The email is logged because it
  is required for the operator to know which account was provisioned.
"""

from __future__ import annotations

import logging
from typing import Literal

from sqlalchemy import select

from app.auth.models import User, UserRole
from app.auth.passwords import hash_password
from app.config import settings
from app.db.session import session_scope

logger = logging.getLogger(__name__)


BootstrapResult = Literal["skipped", "created", "exists", "blocked"]


async def ensure_bootstrap_admin() -> BootstrapResult:
    """Provision the bootstrap admin if its env vars are present.

    Return values match the log line emitted for that path so tests
    and ops alerting can switch on the same vocabulary:

    - ``"skipped"`` env vars absent — no action taken
    - ``"created"`` new admin row inserted
    - ``"exists"``  admin row already present for this email (no-op)
    - ``"blocked"`` email is held by a non-admin user; refused to mutate

    Errors from the DB layer propagate. The caller (lifespan) wraps
    this in its non-fatal try/except so a transient failure here does
    not prevent the API from coming up.
    """
    email = settings.bootstrap_admin_email
    password = settings.bootstrap_admin_password

    if not email or not password:
        logger.info(
            "Bootstrap admin: skipped — BOOTSTRAP_ADMIN_EMAIL/PASSWORD not set"
        )
        return "skipped"

    email_lower = email.lower()

    async with session_scope() as session:
        existing = await session.execute(
            select(User).where(User.email == email_lower)
        )
        user = existing.scalar_one_or_none()

        if user is not None:
            if user.role == UserRole.ADMIN.value:
                logger.info("Bootstrap admin: already exists (%s)", email_lower)
                return "exists"
            # Email taken by a non-admin. Refuse to silently promote —
            # the spec is explicit: never mutate existing users.
            logger.warning(
                "Bootstrap admin: email %s already used by a non-admin user; "
                "refusing to mutate. Pick a different BOOTSTRAP_ADMIN_EMAIL "
                "or promote manually.",
                email_lower,
            )
            return "blocked"

        new_admin = User(
            email=email_lower,
            password_hash=hash_password(password),
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        session.add(new_admin)
        await session.commit()
        logger.info("Bootstrap admin: created (%s)", email_lower)
        return "created"


__all__ = ["BootstrapResult", "ensure_bootstrap_admin"]
