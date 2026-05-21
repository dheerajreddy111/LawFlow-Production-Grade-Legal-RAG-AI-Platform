"""Analytics persistence and aggregation.

- :mod:`app.analytics.models`   QueryEvent SQLAlchemy table
- :mod:`app.analytics.events`   Async helper to record one event
- :mod:`app.analytics.queries`  Read-side aggregations used by the
                                /api/v1/admin/analytics endpoint

The table is append-only by design — we never UPDATE rows. Retention
trimming is a future concern; for now SQLite handles tens of millions
of small rows without trouble.
"""

from app.analytics.events import record_query_event
from app.analytics.models import QueryEvent

__all__ = ["QueryEvent", "record_query_event"]
