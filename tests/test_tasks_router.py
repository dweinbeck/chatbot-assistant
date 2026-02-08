"""Tests for the task handler router endpoints (index-file and delete-file)."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
@patch("app.routers.tasks.index_file", new_callable=AsyncMock)
async def test_index_file_endpoint(mock_index, client: AsyncClient) -> None:
    """POST /tasks/index-file with valid payload calls indexer and returns result."""
    mock_index.return_value = {"status": "indexed", "chunks": 3}

    payload = {
        "repo_owner": "testuser",
        "repo_name": "my-repo",
        "repo_id": 1,
        "path": "src/main.py",
        "commit_sha": "abc123",
    }

    response = await client.post("/tasks/index-file", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "indexed"
    assert data["chunks"] == 3
    mock_index.assert_awaited_once()


@pytest.mark.anyio
@patch("app.routers.tasks.delete_file", new_callable=AsyncMock)
async def test_delete_file_endpoint(mock_delete, client: AsyncClient) -> None:
    """POST /tasks/delete-file with valid payload calls delete and returns result."""
    mock_delete.return_value = {"status": "deleted"}

    payload = {
        "repo_owner": "testuser",
        "repo_name": "my-repo",
        "repo_id": 1,
        "path": "old_file.py",
    }

    response = await client.post("/tasks/delete-file", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "deleted"
    mock_delete.assert_awaited_once()


@pytest.mark.anyio
@patch("app.routers.tasks.index_file", new_callable=AsyncMock)
async def test_index_file_endpoint_error(mock_index, client: AsyncClient) -> None:
    """POST /tasks/index-file returns 500 when indexer raises an exception."""
    mock_index.side_effect = RuntimeError("DB connection failed")

    payload = {
        "repo_owner": "testuser",
        "repo_name": "my-repo",
        "repo_id": 1,
        "path": "src/main.py",
        "commit_sha": "abc123",
    }

    response = await client.post("/tasks/index-file", json=payload)

    assert response.status_code == 500
    assert "Failed to index file" in response.json()["detail"]
