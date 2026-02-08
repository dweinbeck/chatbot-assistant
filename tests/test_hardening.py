"""Tests for production hardening: exception handler, structlog, branch deletion, httpx timeout."""

from __future__ import annotations

import hashlib
import hmac
import inspect
import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

    from app.services.task_queue import InMemoryTaskQueue

# ---------------------------------------------------------------------------
# Helpers (duplicated minimally from test_webhooks to keep tests standalone)
# ---------------------------------------------------------------------------

WEBHOOK_SECRET = "dev-secret"


def _sign(body: bytes, secret: str) -> str:
    """Compute the GitHub-style HMAC-SHA256 signature for a payload."""
    digest = hmac.new(
        secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


# ---------------------------------------------------------------------------
# 1. Global exception handler returns JSON 500
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_global_exception_handler_returns_json() -> None:
    """The unhandled_exception_handler returns JSON with status 500."""
    from unittest.mock import MagicMock

    from app.main import unhandled_exception_handler

    mock_request = MagicMock()
    mock_request.url.path = "/test"
    mock_request.method = "GET"

    response = await unhandled_exception_handler(mock_request, Exception("boom"))

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "Internal server error"}


# ---------------------------------------------------------------------------
# 2. Branch deletion webhook returns early with 0 tasks
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_webhook_branch_deletion_early_return(
    client: AsyncClient,
    mock_task_queue: InMemoryTaskQueue,
) -> None:
    """A push event with deleted=True returns 202 with 0 tasks and skips processing."""
    payload = {
        "ref": "refs/heads/feature-branch",
        "before": "abc0000",
        "after": "0" * 40,
        "repository": {
            "id": 12345,
            "name": "my-repo",
            "full_name": "testuser/my-repo",
            "owner": {"login": "testuser", "name": "Test User"},
            "default_branch": "main",
        },
        "commits": [],
        "head_commit": None,
        "created": False,
        "deleted": True,
        "forced": False,
    }
    body = json.dumps(payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)

    response = await client.post(
        "/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 202
    data = response.json()
    assert data["tasks_enqueued"] == 0
    # Crucially, the task queue must be empty (early return, not empty commits)
    assert len(mock_task_queue.tasks) == 0


# ---------------------------------------------------------------------------
# 3. structlog is configured (smoke test)
# ---------------------------------------------------------------------------


def test_structlog_is_configured() -> None:
    """structlog.get_logger() returns a usable logger without error."""
    import structlog

    logger = structlog.get_logger()
    assert logger is not None


# ---------------------------------------------------------------------------
# 4. httpx.AsyncClient has explicit timeout in task handler
# ---------------------------------------------------------------------------


def test_httpx_client_has_explicit_timeout() -> None:
    """The task handler creates httpx.AsyncClient with an explicit timeout parameter."""
    from app.routers import tasks as tasks_module

    source = inspect.getsource(tasks_module)
    assert "timeout=" in source, "httpx.AsyncClient must have explicit timeout"


# ---------------------------------------------------------------------------
# 5. No stdlib logging.getLogger in migrated source files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_path",
    [
        "app.routers.webhooks",
        "app.routers.tasks",
        "app.routers.chat",
        "app.services.indexer",
    ],
)
def test_no_stdlib_logging(module_path: str) -> None:
    """Migrated modules must use structlog, not stdlib logging.getLogger."""
    import importlib

    module = importlib.import_module(module_path)
    source = inspect.getsource(module)
    assert "logging.getLogger" not in source, f"{module_path} still uses stdlib logging"
    assert "structlog" in source, f"{module_path} should use structlog"
