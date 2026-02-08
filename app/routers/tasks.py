"""Task handler router for processing index and delete file tasks.

These endpoints are called by the task queue (Cloud Tasks or in-memory)
to process individual file indexing and deletion operations.
"""

from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db_session
from app.schemas.tasks import DeleteFilePayload, IndexFilePayload
from app.services.indexer import delete_file, index_file

logger = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/index-file")
async def handle_index_file(
    payload: IndexFilePayload,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Process an index-file task: fetch, filter, chunk, and upsert.

    Called by the task queue for each added or modified file in a push event.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            result = await index_file(
                session=session,
                github_client=client,
                owner=payload.repo_owner,
                repo=payload.repo_name,
                repo_id=payload.repo_id,
                path=payload.path,
                commit_sha=payload.commit_sha,
                token=settings.github_token,
            )
    except Exception:
        logger.exception("index_file_failed", path=payload.path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to index file: {payload.path}",
        ) from None
    return result


@router.post("/delete-file")
async def handle_delete_file(
    payload: DeleteFilePayload,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    """Process a delete-file task: remove the file and its chunks.

    Called by the task queue for each removed file in a push event.
    """
    try:
        result = await delete_file(
            session=session,
            repo_id=payload.repo_id,
            path=payload.path,
        )
    except Exception:
        logger.exception("delete_file_failed", path=payload.path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete file: {payload.path}",
        ) from None
    return result
