"""Pydantic models for admin endpoints."""

from pydantic import BaseModel


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
