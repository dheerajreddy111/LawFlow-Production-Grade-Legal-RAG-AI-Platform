"""Timestamp normalisation helpers.

SQLite drops tzinfo on read even when the column is
``DateTime(timezone=True)``. Postgres preserves it. Code that crosses
DB → API boundaries has been repeating the same coercion inline; these
helpers centralise it so any future change (e.g. storing all UTC as
ISO strings) lives in one place.
"""

from __future__ import annotations

from datetime import datetime, timezone


def as_utc(value: datetime) -> datetime:
    """Return ``value`` as a UTC-aware datetime.

    - Naive input is interpreted as UTC (the DB's storage convention).
    - Aware input is converted to UTC if it isn't already.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    if value.utcoffset() == timezone.utc.utcoffset(value):
        return value
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    """ISO-8601 string with explicit UTC offset, derived from ``value``."""
    return as_utc(value).isoformat()


__all__ = ["as_utc", "iso_utc"]
