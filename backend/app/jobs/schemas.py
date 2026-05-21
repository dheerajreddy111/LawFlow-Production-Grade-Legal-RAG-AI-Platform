"""Pydantic schemas for the jobs surface.

Wire shape only — the admin UI for jobs ships in a later slice.
Keeping these defined now means the persistence helpers can return
typed objects and future endpoints can re-export the same schemas
without churn.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer

from app.jobs.types import JobStatus
from app.utils.time import as_utc


class JobCreate(BaseModel):
    """Input for ``create_job``."""

    type: str
    payload: dict[str, Any] | None = None

    def payload_as_json(self) -> str | None:
        if self.payload is None:
            return None
        return json.dumps(self.payload, separators=(",", ":"))


class JobOut(BaseModel):
    """Wire shape for one job row.

    ``payload`` and ``result`` are decoded on the way out so callers
    don't see raw JSON strings.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    status: JobStatus
    payload: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_serializer("created_at", "started_at", "completed_at")
    def _serialise_dt(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return as_utc(value).isoformat()

    @classmethod
    def from_row(cls, row: Any) -> "JobOut":
        """Decode the row's stringified JSON columns into objects."""
        payload = json.loads(row.payload_json) if row.payload_json else None
        result = json.loads(row.result_json) if row.result_json else None
        return cls(
            id=row.id,
            type=row.type,
            status=JobStatus(row.status),
            payload=payload,
            result=result,
            error=row.error,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )


__all__ = ["JobCreate", "JobOut"]
