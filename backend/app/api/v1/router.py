from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    auth,
    documents,
    evaluation,
    jobs,
    metrics,
    query,
)

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(auth.router,       prefix="/auth",       tags=["Auth"])
v1_router.include_router(query.router,      prefix="/query",      tags=["Query"])
v1_router.include_router(documents.router,  prefix="/documents",  tags=["Documents"])
v1_router.include_router(evaluation.router, prefix="/evaluation", tags=["Evaluation"])
v1_router.include_router(jobs.router,       prefix="/jobs",       tags=["Jobs"])
v1_router.include_router(metrics.router,    prefix="/metrics",    tags=["Metrics"])
v1_router.include_router(admin.router,      prefix="/admin",      tags=["Admin"])
