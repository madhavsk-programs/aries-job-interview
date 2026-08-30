import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes.sessions import router as sessions_router
from api.routes.resume import router as resume_router
from config import settings
from db.session import dispose_engine
from local_ai import local_ai_status
from observability.otel_setup import setup_tracing, shutdown_tracing

logger = logging.getLogger("aries.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_tracing("aries-voice-api")
    logger.info(
        "API up (persistence=%s, tracing=%s)",
        settings.persistence_enabled,
        settings.tracing_enabled,
    )
    yield
    await dispose_engine()
    shutdown_tracing()


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Interview setup, voice access, evidence, replay and reporting for ARIES-Voice.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(sessions_router, prefix="/api")
app.include_router(resume_router, prefix="/api")


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "phase": "complete",
        "persistence": settings.persistence_enabled,
        "tracing": settings.tracing_enabled,
    }


@app.get("/health/ai")
async def health_ai() -> dict[str, object]:
    """Explain exactly which local service/model is missing."""

    return await local_ai_status()
