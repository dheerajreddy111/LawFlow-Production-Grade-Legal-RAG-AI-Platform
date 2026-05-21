"""Async writer for query analytics events.

The writer is **non-fatal by design**: a DB hiccup here must not break
the user's chat. Errors are logged and swallowed.
"""

from __future__ import annotations

import logging

from app.analytics.models import QueryEvent
from app.db.session import session_scope

logger = logging.getLogger(__name__)

# Hard cap so we never spike a row past the column width.
_PREVIEW_MAX = 160


def _preview(query: str) -> str:
    if not query:
        return ""
    q = query.strip()
    if len(q) <= _PREVIEW_MAX:
        return q
    return q[: _PREVIEW_MAX - 1] + "…"


async def record_query_event(
    *,
    user_id: int | None,
    session_id: str | None,
    query: str,
    intent: str,
    route: str,
    confidence: float,
    latency_ms: float,
    has_error: bool = False,
    domain: str | None = None,
    error_reason: str | None = None,
) -> None:
    """Persist one event. Never raises — analytics are best-effort."""
    try:
        async with session_scope() as session:
            session.add(
                QueryEvent(
                    user_id=user_id,
                    session_id=session_id,
                    intent=intent[:64] if intent else "",
                    route=route[:32] if route else "",
                    confidence=float(confidence),
                    latency_ms=float(latency_ms),
                    has_error=bool(has_error),
                    query_preview=_preview(query),
                    domain=(domain or None) and domain[:64],
                    error_reason=(error_reason or None) and error_reason[:255],
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 — boundary: analytics are best-effort
        logger.exception("Failed to record query event (analytics)")
