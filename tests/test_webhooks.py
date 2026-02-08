"""Tests for the GitHub webhook endpoint with HMAC-SHA256 signature verification."""

import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient

from app.services.task_queue import InMemoryTaskQueue


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
    num_commits: int = 1,
    added: list[str] | None = None,
    modified: list[str] | None = None,
    removed: list[str] | None = None,
) -> dict:
    """Build a realistic GitHub push webhook payload.

    When ``num_commits`` is used, each commit has one added file.
    For fine-grained control, pass ``added``/``modified``/``removed``
    to create a single commit with those exact file lists.
    """
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
    return {
        "ref": "refs/heads/main",
        "before": "0000000000000000000000000000000000000000",
        "after": "abc0000",
        "repository": {
            "id": 12345,
            "name": "my-repo",
            "full_name": "testuser/my-repo",
            "owner": {"login": "testuser", "name": "Test User"},
            "default_branch": "main",
        },
        "commits": commits,
        "head_commit": commits[-1] if commits else None,
        "created": False,
        "deleted": False,
        "forced": False,
    }


WEBHOOK_SECRET = "dev-secret"
ENDPOINT = "/webhooks/github"


# ---------------------------------------------------------------------------
# Signature verification tests (existing from 02-01)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_webhook_valid_signature(client: AsyncClient) -> None:
    """POST with correct HMAC-SHA256 signature returns 202 and accepted status."""
    payload = _make_push_payload()
    body = json.dumps(payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)

    response = await client.post(
        ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    assert data["tasks_enqueued"] == 1


@pytest.mark.anyio
async def test_webhook_invalid_signature(client: AsyncClient) -> None:
    """POST with an incorrect signature returns 401."""
    payload = _make_push_payload()
    body = json.dumps(payload).encode()
    bad_signature = _sign(body, "wrong-secret")

    response = await client.post(
        ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": bad_signature,
        },
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_webhook_missing_signature(client: AsyncClient) -> None:
    """POST without X-Hub-Signature-256 header returns 422 (missing required header)."""
    payload = _make_push_payload()
    body = json.dumps(payload).encode()

    response = await client.post(
        ENDPOINT,
        content=body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


@pytest.mark.anyio
async def test_webhook_parses_push_payload(client: AsyncClient) -> None:
    """POST with valid signature and multiple commits returns correct task count."""
    payload = _make_push_payload(num_commits=3)
    body = json.dumps(payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)

    response = await client.post(
        ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "accepted"
    # 3 commits, each with 1 added file => 3 index tasks
    assert data["tasks_enqueued"] == 3


# ---------------------------------------------------------------------------
# Task enqueue tests (new for 02-04)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_webhook_enqueues_index_tasks(
    client: AsyncClient, mock_task_queue: InMemoryTaskQueue,
) -> None:
    """Push with 2 added files enqueues 2 index tasks."""
    payload = _make_push_payload(added=["src/a.py", "src/b.py"])
    body = json.dumps(payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)

    response = await client.post(
        ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 202
    assert len(mock_task_queue.tasks) == 2
    for task in mock_task_queue.tasks:
        assert "/tasks/index-file" in task["url"]
        assert task["payload"]["repo_id"] == 12345
        assert task["payload"]["commit_sha"] == "abc0000"


@pytest.mark.anyio
async def test_webhook_enqueues_delete_tasks(
    client: AsyncClient, mock_task_queue: InMemoryTaskQueue,
) -> None:
    """Push with 1 removed file enqueues 1 delete task."""
    payload = _make_push_payload(removed=["old_file.py"])
    body = json.dumps(payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)

    response = await client.post(
        ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 202
    assert len(mock_task_queue.tasks) == 1
    task = mock_task_queue.tasks[0]
    assert "/tasks/delete-file" in task["url"]
    assert task["payload"]["path"] == "old_file.py"


@pytest.mark.anyio
async def test_webhook_mixed_operations(
    client: AsyncClient, mock_task_queue: InMemoryTaskQueue,
) -> None:
    """Push with added + modified + removed files enqueues correct task types."""
    payload = _make_push_payload(
        added=["new.py"],
        modified=["changed.py"],
        removed=["deleted.py"],
    )
    body = json.dumps(payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)

    response = await client.post(
        ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 202
    data = response.json()
    assert data["tasks_enqueued"] == 3

    # 2 index tasks (added + modified) and 1 delete task
    index_tasks = [t for t in mock_task_queue.tasks if "/index-file" in t["url"]]
    delete_tasks = [t for t in mock_task_queue.tasks if "/delete-file" in t["url"]]
    assert len(index_tasks) == 2
    assert len(delete_tasks) == 1

    index_paths = {t["payload"]["path"] for t in index_tasks}
    assert index_paths == {"new.py", "changed.py"}
    assert delete_tasks[0]["payload"]["path"] == "deleted.py"
