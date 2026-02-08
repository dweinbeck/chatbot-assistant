"""Tests for the GitHub API client functions."""

import httpx
import pytest

from app.services.github_client import (
    fetch_file_content,
    get_repo_metadata,
    list_repo_files,
)


@pytest.mark.asyncio
async def test_fetch_file_content_success() -> None:
    """A 200 response returns the raw file text."""
    expected = "def hello():\n    return 'world'\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=expected)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_file_content(
            client, "owner", "repo", "src/main.py", "abc123", "ghp_token"
        )

    assert result == expected


@pytest.mark.asyncio
async def test_fetch_file_content_not_found() -> None:
    """A 404 response returns None instead of raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_file_content(
            client, "owner", "repo", "deleted.py", "abc123", "ghp_token"
        )

    assert result is None


@pytest.mark.asyncio
async def test_fetch_file_content_sends_correct_headers() -> None:
    """The request includes Authorization, Accept, API version, and ref query param."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, text="content")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await fetch_file_content(
            client, "myorg", "myrepo", "lib/utils.ts", "deadbeef", "ghp_secret"
        )

    assert len(captured) == 1
    req = captured[0]

    assert req.headers["authorization"] == "Bearer ghp_secret"
    assert req.headers["accept"] == "application/vnd.github.raw+json"
    assert req.headers["x-github-api-version"] == "2022-11-28"
    assert "ref=deadbeef" in str(req.url)
    assert "/myorg/myrepo/contents/lib/utils.ts" in str(req.url)


@pytest.mark.asyncio
async def test_fetch_file_content_raises_on_server_error() -> None:
    """A 500 response raises httpx.HTTPStatusError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await fetch_file_content(client, "owner", "repo", "file.py", "abc123", "ghp_token")

    assert exc_info.value.response.status_code == 500


# ---------------------------------------------------------------------------
# get_repo_metadata tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_repo_metadata_returns_json() -> None:
    """A 200 response returns the parsed JSON dict."""
    meta = {"id": 42, "default_branch": "main", "full_name": "owner/repo"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=meta)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await get_repo_metadata(client, "owner", "repo", "ghp_token")

    assert result["id"] == 42
    assert result["default_branch"] == "main"


@pytest.mark.asyncio
async def test_get_repo_metadata_raises_on_404() -> None:
    """A 404 response raises httpx.HTTPStatusError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await get_repo_metadata(client, "owner", "nope", "ghp_token")


# ---------------------------------------------------------------------------
# list_repo_files tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_repo_files_returns_blob_paths() -> None:
    """Only blob entries are returned, tree entries are filtered out."""
    tree_data = {
        "sha": "abc123",
        "tree": [
            {"path": "src", "type": "tree"},
            {"path": "src/main.py", "type": "blob"},
            {"path": "README.md", "type": "blob"},
            {"path": "tests", "type": "tree"},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "recursive=1" in str(request.url)
        return httpx.Response(200, json=tree_data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await list_repo_files(client, "owner", "repo", "main", "ghp_token")

    assert result == ["src/main.py", "README.md"]


@pytest.mark.asyncio
async def test_list_repo_files_empty_tree() -> None:
    """An empty tree returns an empty list."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"sha": "abc", "tree": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await list_repo_files(client, "owner", "repo", "main", "ghp_token")

    assert result == []
