"""Pydantic models for Cloud Tasks payloads."""

from pydantic import BaseModel


class IndexFilePayload(BaseModel):
    """Payload for index-file tasks enqueued by the webhook handler."""

    repo_owner: str
    repo_name: str
    repo_id: int
    path: str
    commit_sha: str


class DeleteFilePayload(BaseModel):
    """Payload for delete-file tasks enqueued when files are removed."""

    repo_owner: str
    repo_name: str
    repo_id: int
    path: str
