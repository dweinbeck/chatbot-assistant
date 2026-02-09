"""Pydantic models for admin endpoints."""

from pydantic import BaseModel, Field


class SyncRepoRequest(BaseModel):
    """Request body for POST /admin/sync-repo."""

    owner: str
    repo: str
    ref: str = "main"


class SyncRepoResponse(BaseModel):
    """Response body for POST /admin/sync-repo."""

    status: str
    repo_id: int
    files_found: int
    tasks_enqueued: int
    files_skipped_denylist: int


class BackfillRepoItem(BaseModel):
    """A single repo to backfill."""

    owner: str
    repo: str
    ref: str = "main"


class BackfillRequest(BaseModel):
    """Request body for POST /admin/backfill."""

    repos: list[BackfillRepoItem] = Field(..., min_length=1)


class BackfillRepoResult(BaseModel):
    """Per-repo result from a backfill operation."""

    owner: str
    repo: str
    status: str
    files_found: int = 0
    tasks_enqueued: int = 0
    files_skipped_denylist: int = 0
    error: str | None = None


class BackfillResponse(BaseModel):
    """Response body for POST /admin/backfill."""

    results: list[BackfillRepoResult]
    total_tasks_enqueued: int


class IngestURLRequest(BaseModel):
    """Request body for POST /admin/ingest-url."""

    url: str
    repo_owner: str
    repo_name: str
    path: str | None = None


class IngestURLResponse(BaseModel):
    """Response body for POST /admin/ingest-url."""

    status: str
    chunks_created: int
