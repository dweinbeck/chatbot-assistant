"""FastAPI application factory with lifespan context manager."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db.engine import dispose_engine, init_engine
from app.routers import chat, health, tasks, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifespan: initialize and dispose database engine."""
    await init_engine(settings.database_url)
    yield
    await dispose_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(health.router)
app.include_router(webhooks.router)
app.include_router(tasks.router)
app.include_router(chat.router)
