"""Job status enum.

Stored as the lowercase string value on the ``jobs.status`` column so
the DB row is human-readable. Adding new statuses is intentionally
high-friction: each one corresponds to a new lifecycle transition the
admin UI must learn to render.
"""

from __future__ import annotations

import enum


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.COMPLETED, JobStatus.FAILED)


__all__ = ["JobStatus"]
