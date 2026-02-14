"""End-to-end integration tests for the webhook -> task -> index -> chat pipeline.

Exercises the full flow as an integrated sequence using the mock infrastructure
from conftest.py (mock_db_session, mock_task_queue, mock_gemini_client, client).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from app.services.retrieval import RetrievedChunk

if TYPE_CHECKING:
    from httpx import AsyncClient

    from app.services.gemini_client import InMemoryLLMClient
    from app.services.task_queue import InMemoryTaskQueue

WEBHOOK_SECRET = "dev-secret"
WEBHOOK_ENDPOINT = "/webhooks/github"

_DEFAULT_SHA = "abc1234567890123456789012345678901234567"


# ---------------------------------------------------------------------------
# Helper functions (self-contained copies from test_webhooks / test_chat_router)
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
    num_commits: int = 1,
    added: list[str] | None = None,
    modified: list[str] | None = None,
    removed: list[str] | None = None,
) -> dict:
    """Build a realistic GitHub push webhook payload."""
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


def _make_chunk(
    id: int = 1,  # noqa: A002
    repo_owner: str = "testowner",
    repo_name: str = "testrepo",
    path: str = "src/main.py",
    commit_sha: str = _DEFAULT_SHA,
    start_line: int = 1,
    end_line: int = 10,
    content: str = "def hello():\n    return 'world'",
    score: float = 0.5,
) -> RetrievedChunk:
    """Build a RetrievedChunk with sensible defaults for testing."""
    return RetrievedChunk(
        id=id,
        repo_owner=repo_owner,
        repo_name=repo_name,
        path=path,
        commit_sha=commit_sha,
        start_line=start_line,
        end_line=end_line,
        content=content,
        score=score,
    )


def _citation_source(chunk: RetrievedChunk) -> str:
    """Build the citation source string for a chunk."""
    return (
        f"{chunk.repo_owner}/{chunk.repo_name}/{chunk.path}"
        f"@{chunk.commit_sha}:{chunk.start_line}-{chunk.end_line}"
    )


def _llm_response_json(
    answer: str = "test answer",
    citations: list[dict] | None = None,
    needs_clarification: bool = False,
    clarifying_question: str | None = None,
) -> str:
    """Build a valid LLMResponse JSON string."""
    return json.dumps(
        {
            "answer": answer,
            "citations": citations or [],
            "needs_clarification": needs_clarification,
            "clarifying_question": clarifying_question,
        }
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_full_pipeline_webhook_to_chat(
    client: AsyncClient,
    mock_task_queue: InMemoryTaskQueue,
    mock_gemini_client: InMemoryLLMClient,
) -> None:
    """Full pipeline: webhook POST -> task enqueue -> task handler -> chat with citations."""
    # ---- Step 1: POST webhook with 1 added file ----
    payload = _make_push_payload(added=["src/main.py"])
    body = json.dumps(payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)

    wh_resp = await client.post(
        WEBHOOK_ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert wh_resp.status_code == 202
    wh_data = wh_resp.json()
    assert wh_data["tasks_enqueued"] == 1
    assert len(mock_task_queue.tasks) == 1

    task = mock_task_queue.tasks[0]
    assert "/tasks/index-file" in task["url"]
    assert task["payload"]["repo_id"] == 12345
    assert task["payload"]["path"] == "src/main.py"
    assert task["payload"]["commit_sha"] == "abc0000"

    # ---- Step 2: POST the enqueued task to /tasks/index-file ----
    task_payload = task["payload"]
    with patch(
        "app.routers.tasks.index_file",
        new_callable=AsyncMock,
        return_value={"status": "indexed", "chunks": 3},
    ):
        idx_resp = await client.post("/tasks/index-file", json=task_payload)

    assert idx_resp.status_code == 200
    assert idx_resp.json()["status"] == "indexed"

    # ---- Step 3: POST chat question referencing the indexed file ----
    chunks = [
        _make_chunk(id=1, path="src/main.py", start_line=1, end_line=10, score=0.5),
        _make_chunk(id=2, path="src/main.py", start_line=11, end_line=20, score=0.3),
        _make_chunk(id=3, path="src/main.py", start_line=21, end_line=30, score=0.2),
    ]

    citations = [
        {"source": _citation_source(chunks[0]), "relevance": "defines main entry"},
        {"source": _citation_source(chunks[1]), "relevance": "initialisation logic"},
    ]
    mock_gemini_client.response = _llm_response_json(
        answer="main.py defines the application entry point.",
        citations=citations,
    )

    with patch(
        "app.routers.chat.retrieve_chunks",
        new_callable=AsyncMock,
        return_value=chunks,
    ):
        chat_resp = await client.post("/chat", json={"question": "What does main.py do?"})

    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()
    assert len(chat_data["citations"]) > 0
    assert chat_data["confidence"] in ("medium", "high")
    assert "main.py" in chat_data["answer"].lower()


@pytest.mark.anyio
async def test_pipeline_webhook_with_multiple_files(
    client: AsyncClient,
    mock_task_queue: InMemoryTaskQueue,
) -> None:
    """Webhook with 2 added + 1 modified file enqueues 3 tasks with correct payloads."""
    payload = _make_push_payload(
        added=["src/a.py", "src/b.py"],
        modified=["src/c.py"],
    )
    body = json.dumps(payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)

    response = await client.post(
        WEBHOOK_ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 202
    assert response.json()["tasks_enqueued"] == 3
    assert len(mock_task_queue.tasks) == 3

    # All tasks should share the same commit_sha (payload.after)
    for task in mock_task_queue.tasks:
        assert task["payload"]["commit_sha"] == "abc0000"

    enqueued_paths = {t["payload"]["path"] for t in mock_task_queue.tasks}
    assert enqueued_paths == {"src/a.py", "src/b.py", "src/c.py"}


@pytest.mark.anyio
async def test_pipeline_delete_file_flow(
    client: AsyncClient,
    mock_task_queue: InMemoryTaskQueue,
) -> None:
    """Webhook with 1 removed file -> enqueue delete task -> task handler processes it."""
    # ---- Step 1: POST webhook with 1 removed file ----
    payload = _make_push_payload(removed=["old_module.py"])
    body = json.dumps(payload).encode()
    signature = _sign(body, WEBHOOK_SECRET)

    wh_resp = await client.post(
        WEBHOOK_ENDPOINT,
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
    )

    assert wh_resp.status_code == 202
    assert len(mock_task_queue.tasks) == 1

    task = mock_task_queue.tasks[0]
    assert "/tasks/delete-file" in task["url"]
    assert task["payload"]["path"] == "old_module.py"

    # ---- Step 2: POST the delete task to /tasks/delete-file ----
    with patch(
        "app.routers.tasks.delete_file",
        new_callable=AsyncMock,
        return_value={"status": "deleted"},
    ):
        del_resp = await client.post("/tasks/delete-file", json=task["payload"])

    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"
