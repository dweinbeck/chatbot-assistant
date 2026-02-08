"""Edge case tests for webhook, task handler, and chat boundary conditions.

Covers: branch deletion, tag push, empty commits, malformed JSON, missing
fields, large pushes, handler exceptions, whitespace questions, and
concurrent requests.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient

    from app.services.gemini_client import InMemoryLLMClient
    from app.services.task_queue import InMemoryTaskQueue

WEBHOOK_SECRET = "dev-secret"
WEBHOOK_ENDPOINT = "/webhooks/github"


# ---------------------------------------------------------------------------
# Helper functions (self-contained copies from test_webhooks)
# ---------------------------------------------------------------------------


def _sign(body: bytes, secret: str) -> str:
    """Compute the GitHub-style HMAC-SHA256 signature for a payload."""
    digest = hmac.new(
        secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _make_push_payload(
    *,
    ref: str = "refs/heads/main",
    before: str = "0000000000000000000000000000000000000000",
    after: str = "abc0000",
    deleted: bool = False,
    num_commits: int = 1,
    added: list[str] | None = None,
    modified: list[str] | None = None,
    removed: list[str] | None = None,
    head_commit: dict | None | object = ...,
) -> dict:
    """Build a realistic GitHub push webhook payload with extra control."""
    if added is not None or modified is not None or removed is not None:
        commits = [
            {
                "id": "abc0001",
                "message": "test commit",
                "timestamp": "2026-02-07T12:00:00Z",
                "added": added or [],
                "modified": modified or [],
                "removed": removed or [],
                "author": {"name": "Test User", "email": "test@example.com"},
            }
        ]
    else:
        commits = [
            {
                "id": f"abc{i:04d}",
                "message": f"commit {i}",
                "timestamp": "2026-02-07T12:00:00Z",
                "added": [f"file{i}.py"],
                "modified": [],
                "removed": [],
                "author": {"name": "Test User", "email": "test@example.com"},
            }
            for i in range(num_commits)
        ]

    # Determine head_commit: use sentinel to auto-derive, None for explicit null
    hc = (commits[-1] if commits else None) if head_commit is ... else head_commit

    return {
        "ref": ref,
        "before": before,
        "after": after,
        "repository": {
            "id": 12345,
            "name": "my-repo",
            "full_name": "testuser/my-repo",
            "owner": {"login": "testuser", "name": "Test User"},
            "default_branch": "main",
        },
        "commits": commits,
        "head_commit": hc,
        "created": False,
        "deleted": deleted,
        "forced": False,
    }


def _post_webhook(client: AsyncClient, payload: dict) -> object:
    """Send a signed webhook POST and return the awaitable response."""
    body = json.dumps(payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)
    return client.post(
        WEBHOOK_ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )


# ---------------------------------------------------------------------------
# Webhook edge cases
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_webhook_branch_deletion(
    client: AsyncClient,
    mock_task_queue: InMemoryTaskQueue,
) -> None:
    """Branch deletion webhook: deleted=True, zero-sha after, empty commits -> 0 tasks."""
    payload = _make_push_payload(
        deleted=True,
        after="0000000000000000000000000000000000000000",
        num_commits=0,
        added=[],
        head_commit=None,
    )
    # Force commits to empty list (the helper creates one commit with added=[])
    payload["commits"] = []

    response = await _post_webhook(client, payload)

    assert response.status_code == 202
    data = response.json()
    assert data["tasks_enqueued"] == 0
    assert len(mock_task_queue.tasks) == 0


@pytest.mark.anyio
async def test_webhook_tag_push(
    client: AsyncClient,
    mock_task_queue: InMemoryTaskQueue,
) -> None:
    """Tag push (refs/tags/) is processed normally -- handler doesn't distinguish."""
    payload = _make_push_payload(
        ref="refs/tags/v1.0.0",
        num_commits=1,
    )

    response = await _post_webhook(client, payload)

    assert response.status_code == 202
    data = response.json()
    assert data["tasks_enqueued"] == 1
    assert len(mock_task_queue.tasks) == 1


@pytest.mark.anyio
async def test_webhook_empty_commits(
    client: AsyncClient,
    mock_task_queue: InMemoryTaskQueue,
) -> None:
    """Push with empty commits list but deleted=False -> 0 tasks enqueued."""
    payload = _make_push_payload(num_commits=0, added=[])
    payload["commits"] = []

    response = await _post_webhook(client, payload)

    assert response.status_code == 202
    data = response.json()
    assert data["tasks_enqueued"] == 0
    assert len(mock_task_queue.tasks) == 0


@pytest.mark.anyio
async def test_webhook_malformed_json(client: AsyncClient) -> None:
    """Non-JSON body with valid HMAC signature returns JSON 500.

    The webhook handler calls model_validate_json() inside the route (not via
    FastAPI parameter injection), so Pydantic's ValidationError is caught by
    the global exception handler and returned as a JSON 500 response.
    """
    body = b"not-json"
    signature = _sign(body, WEBHOOK_SECRET)

    response = await client.post(
        WEBHOOK_ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 500
    data = response.json()
    assert data["detail"] == "Internal server error"


@pytest.mark.anyio
async def test_webhook_missing_required_fields(client: AsyncClient) -> None:
    """Valid JSON missing required fields returns JSON 500.

    Same root cause as malformed JSON -- model_validate_json inside route handler.
    The global exception handler catches the ValidationError and returns JSON 500.
    """
    partial_payload = {"ref": "refs/heads/main"}
    body = json.dumps(partial_payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)

    response = await client.post(
        WEBHOOK_ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 500
    data = response.json()
    assert data["detail"] == "Internal server error"


@pytest.mark.anyio
async def test_webhook_large_push_many_files(
    client: AsyncClient,
    mock_task_queue: InMemoryTaskQueue,
) -> None:
    """Single commit with 20 added files enqueues 20 tasks."""
    files = [f"src/module_{i:02d}.py" for i in range(20)]
    payload = _make_push_payload(added=files)

    response = await _post_webhook(client, payload)

    assert response.status_code == 202
    data = response.json()
    assert data["tasks_enqueued"] == 20
    assert len(mock_task_queue.tasks) == 20

    enqueued_paths = {t["payload"]["path"] for t in mock_task_queue.tasks}
    assert enqueued_paths == set(files)


# ---------------------------------------------------------------------------
# Task handler edge cases
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_index_file_handler_exception_returns_500(
    client: AsyncClient,
) -> None:
    """index_file raising RuntimeError -> 500 with JSON detail (not HTML)."""
    task_payload = {
        "repo_owner": "testuser",
        "repo_name": "my-repo",
        "repo_id": 12345,
        "path": "src/main.py",
        "commit_sha": "abc0000",
    }

    with patch(
        "app.routers.tasks.index_file",
        new_callable=AsyncMock,
        side_effect=RuntimeError("GitHub API failed"),
    ):
        response = await client.post("/tasks/index-file", json=task_payload)

    assert response.status_code == 500
    data = response.json()
    assert "detail" in data


@pytest.mark.anyio
async def test_delete_file_handler_exception_returns_500(
    client: AsyncClient,
) -> None:
    """delete_file raising RuntimeError -> 500 with JSON detail (not HTML)."""
    task_payload = {
        "repo_owner": "testuser",
        "repo_name": "my-repo",
        "repo_id": 12345,
        "path": "old_file.py",
    }

    with patch(
        "app.routers.tasks.delete_file",
        new_callable=AsyncMock,
        side_effect=RuntimeError("DB error"),
    ):
        response = await client.post("/tasks/delete-file", json=task_payload)

    assert response.status_code == 500
    data = response.json()
    assert "detail" in data


# ---------------------------------------------------------------------------
# Chat edge cases
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_whitespace_question(
    mock_retrieve: AsyncMock,
    client: AsyncClient,
) -> None:
    """Whitespace-only question (3 spaces) passes min_length=1 and gets empty retrieval."""
    mock_retrieve.return_value = []

    response = await client.post("/chat", json={"question": "   "})

    assert response.status_code == 200
    data = response.json()
    assert "I don't know" in data["answer"]


@pytest.mark.anyio
@patch("app.routers.chat.retrieve_chunks", new_callable=AsyncMock)
async def test_chat_concurrent_requests(
    mock_retrieve: AsyncMock,
    client: AsyncClient,
    mock_gemini_client: InMemoryLLMClient,
) -> None:
    """5 concurrent chat requests all return 200 with no shared-state issues."""
    mock_retrieve.return_value = []

    async def _send_chat(question: str) -> int:
        resp = await client.post("/chat", json={"question": question})
        return resp.status_code

    results = await asyncio.gather(*[
        _send_chat(f"Question number {i}") for i in range(5)
    ])

    assert all(code == 200 for code in results)
    assert len(results) == 5
