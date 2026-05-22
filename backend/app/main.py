import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.v1.router import v1_router
from app.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


async def _init_auth_db() -> None:
    """Run schema migrations and (optionally) provision the bootstrap admin.

    Production schema management is owned by Alembic — ``upgrade_to_head``
    invokes ``alembic upgrade head`` programmatically. The bootstrap
    admin is a separate concern handled by
    :func:`app.auth.bootstrap.ensure_bootstrap_admin` (idempotent,
    refuses to mutate existing users).

    Failure is logged but never crashes the API — anonymous read paths
    still function on a partial init.
    """
    from app.auth.bootstrap import ensure_bootstrap_admin
    from app.db.migrations import upgrade_to_head

    await upgrade_to_head()
    await ensure_bootstrap_admin()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "LawFlow API starting  env=%s  version=%s",
        settings.environment,
        settings.version,
    )

    # Auth / persistence — tables + optional bootstrap admin.
    try:
        await _init_auth_db()
    except Exception:  # noqa: BLE001 — boundary: never break startup
        logger.exception("Auth DB init failed; auth endpoints may be unavailable")

    # Initialise LangSmith tracing if configured. No-op when keys are
    # absent (the integration is fully optional — see
    # app/integrations/lc/settings.py for env contract).
    try:
        from app.integrations.lc import configure_langsmith

        configure_langsmith()
    except Exception:  # noqa: BLE001 — boundary: never break startup
        logger.exception("LangSmith setup failed; continuing without tracing")

    # Register background-job handlers. The import is the registration —
    # see app/jobs/handlers.py. Kept inside lifespan so test suites that
    # construct multiple apps don't double-register.
    try:
        from app.jobs import handlers as _job_handlers  # noqa: F401

        # Schedule retention/cleanup sweeps if enabled (cheap async task on
        # the API process's loop — see app/jobs/cleanup.py for the policy).
        from app.jobs.cleanup import start_retention_loop

        retention_task = start_retention_loop()
    except Exception:  # noqa: BLE001 — boundary: never break startup
        logger.exception("Background-job init failed; continuing without jobs")
        retention_task = None

    # Ingest the legal corpora into the vector store so rag-routed queries
    # have a populated index. Idempotent and non-fatal — a failure here must
    # not block the API (deterministic retrieval still works without it).
    try:
        from app.rag.ingest import ingest_corpora

        count = await ingest_corpora()
        logger.info("Vector store ready: %d corpus chunks", count)
    except Exception:  # noqa: BLE001 — boundary: never break startup
        logger.exception(
            "Corpus ingestion failed; continuing with deterministic retrieval"
        )

    # Warm the BM25 lexical index alongside the vector store. The first
    # query would otherwise pay the build cost (a few hundred ms for a
    # ~1k-chunk corpus). Failing to load BM25 is recoverable: the hybrid
    # retriever will lazily rebuild on first use.
    try:
        from app.rag.bm25 import bm25_index

        n = await bm25_index().refresh()
        logger.info("BM25 index ready: %d active chunks", n)
    except Exception:  # noqa: BLE001 — boundary: never break startup
        logger.exception("BM25 index warm failed; will retry on first query")
    yield
    # Cancel the retention loop so the process can shut down cleanly even
    # mid-sleep. Best-effort — a failure here just lets the task die with
    # the loop.
    if retention_task is not None:
        retention_task.cancel()
    logger.info("LawFlow API shutting down")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=settings.description,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Temporary wildcard for deployment stabilization. Revert to
    # settings.cors_origins once CORS_ORIGINS is configured on Railway with
    # the Vercel domain.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(v1_router)

    return app


app = create_app()
