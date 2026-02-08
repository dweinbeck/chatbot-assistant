"""FastAPI application factory with lifespan context manager."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db.engine import dispose_engine, init_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifespan: initialize and dispose database engine."""
    await init_engine(settings.database_url)
    yield
    await dispose_engine()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
