"""Pydantic models for GitHub webhook payloads."""

from pydantic import BaseModel, Field


class CommitAuthor(BaseModel):
    """Author information from a Git commit."""

    name: str
    email: str


class Commit(BaseModel):
    """A single commit within a GitHub push event."""

    id: str
    message: str
    timestamp: str
    added: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    author: CommitAuthor


class RepositoryOwner(BaseModel):
    """Owner of the repository (user or organization)."""

    login: str | None = None
    name: str | None = None


class Repository(BaseModel):
    """Repository metadata from the webhook payload."""

    id: int
    name: str
    full_name: str
    owner: RepositoryOwner
    default_branch: str = "main"


class PushWebhookPayload(BaseModel):
    """GitHub push webhook event payload.

    Reference: https://docs.github.com/en/webhooks/webhook-events-and-payloads#push
    """

    ref: str
    before: str
    after: str
    repository: Repository
    commits: list[Commit] = Field(default_factory=list)
    head_commit: Commit | None = None
    created: bool = False
    deleted: bool = False
    forced: bool = False
