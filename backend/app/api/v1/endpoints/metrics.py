"""GET /api/v1/metrics — JSON snapshot of in-process metrics.

Returns counters (queries, ingestion, errors), latency histograms
(process_query, ingest, retrieval, generation), and process uptime.
This is *operational* observability — for product analytics, lean on
the LangSmith traces (which are richer and persistent).

The ``/prometheus`` subroute exposes the same data in Prometheus's
text-exposition v0.0.4 format so a single-node deployment can be
scraped by a standard Prometheus server without us pulling in the
official client library.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app.auth import User, require_admin
from app.services.metrics import metrics

router = APIRouter()


@router.get(
    "",
    summary="In-process metrics snapshot (counters + latency histograms)",
)
async def get_metrics(
    _admin: Annotated[User, Depends(require_admin)],
) -> dict:
    return metrics.snapshot()


@router.get(
    "/prometheus",
    summary="Prometheus text-exposition v0.0.4 of the same metrics",
    response_class=PlainTextResponse,
    responses={
        200: {
            "content": {
                "text/plain; version=0.0.4; charset=utf-8": {
                    "example": "# HELP lawflow_uptime_seconds Process uptime in seconds\n"
                }
            }
        }
    },
)
async def get_metrics_prometheus(
    _admin: Annotated[User, Depends(require_admin)],
) -> PlainTextResponse:
    text = metrics.prometheus_text()
    # The version=0.0.4 + charset attributes are part of the standard
    # exposition contract — a Prometheus scraper inspects them to pick
    # the parser version.
    return PlainTextResponse(
        text, media_type="text/plain; version=0.0.4; charset=utf-8"
    )
