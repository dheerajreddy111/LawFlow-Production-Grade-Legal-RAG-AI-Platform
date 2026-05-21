import time

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(tags=["System"])

_start_time = time.monotonic()


class RootResponse(BaseModel):
    service: str
    version: str
    description: str
    environment: str
    docs: str
    health: str


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    uptime_seconds: float


@router.get("/", response_model=RootResponse, summary="API root")
async def root() -> RootResponse:
    return RootResponse(
        service=settings.app_name,
        version=settings.version,
        description=settings.description,
        environment=settings.environment,
        docs="/docs",
        health="/health",
    )


@router.get("/health", response_model=HealthResponse, summary="Health check")
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.version,
        environment=settings.environment,
        uptime_seconds=round(time.monotonic() - _start_time, 2),
    )
