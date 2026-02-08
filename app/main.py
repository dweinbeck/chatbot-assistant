"""FastAPI application factory with lifespan context manager."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.engine import dispose_engine, init_engine
from app.logging_config import configure_logging
from app.routers import admin, chat, health, tasks, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifespan: initialize and dispose database engine."""
    configure_logging(json_logs=not settings.debug, log_level=settings.log_level)
    await init_engine(settings.database_url)

    if settings.gcp_project:
        from app.dependencies import init_production_deps

        init_production_deps(
            gcp_project=settings.gcp_project,
            gcp_location=settings.gcp_location,
            gemini_model=settings.gemini_model,
            cloud_tasks_queue=settings.cloud_tasks_queue,
        )

    yield
    await dispose_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

if settings.cors_origins:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a JSON 500 response for any unhandled exception."""
    logger = structlog.get_logger()
    logger.exception("unhandled_exception", path=request.url.path, method=request.method)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(tasks.router)
app.include_router(chat.router)
app.include_router(admin.router)
