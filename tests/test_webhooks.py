"""Tests for the GitHub webhook endpoint with HMAC-SHA256 signature verification."""

import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient


def _sign(body: bytes, secret: str) -> str:
    """Compute the GitHub-style HMAC-SHA256 signature for a payload."""
    digest = hmac.new(
        secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"


def _make_push_payload(*, num_commits: int = 1) -> dict:
    """Build a realistic GitHub push webhook payload."""
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
    assert data["commits"] == 1


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
    """POST with valid signature and multiple commits returns correct commit count."""
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
    assert data["commits"] == 3
