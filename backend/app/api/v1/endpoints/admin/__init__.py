"""Admin dashboard router — composed from per-section modules.

The v1 router mounts the aggregated ``router`` below at ``/admin`` with
``tags=["Admin"]``. Each sub-module owns one section of the dashboard:

- ``overview.py``    Headline KPIs   (GET /overview)
- ``documents.py``   Document mgmt   (GET /documents, GET/DELETE /documents/{source})
- ``system.py``      System health   (GET /system)
- ``analytics.py``   Query analytics (GET /analytics)
- ``evaluation.py``  Eval history    (GET /evaluation/runs, GET/DELETE /evaluation/runs/{run_id})

Splitting was a pure mechanical refactor — every path, response model,
RBAC dependency, and OpenAPI tag is preserved.
"""

from fastapi import APIRouter

from app.api.v1.endpoints.admin import (
    analytics,
    documents,
    evaluation,
    overview,
    system,
)

router = APIRouter()
router.include_router(overview.router)
router.include_router(documents.router)
router.include_router(system.router)
router.include_router(analytics.router)
router.include_router(evaluation.router)

__all__ = ["router"]
