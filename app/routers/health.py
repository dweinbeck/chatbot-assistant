"""Health check endpoint with database connectivity verification."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.schemas.health import HealthResponse

router = APIRouter()

DBSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/healthz", response_model=HealthResponse)
async def healthz(db: DBSession) -> HealthResponse:
    """Check application health and database connectivity.

    Executes a simple SELECT 1 query to verify the database is reachable.
    Returns 200 with status info on success; lets exceptions propagate as 500.
    """
    await db.execute(text("SELECT 1"))
    return HealthResponse(status="ok", database="connected")
