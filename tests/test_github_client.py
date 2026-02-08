"""Tests for the GitHub file content client."""

import httpx
import pytest

from app.services.github_client import fetch_file_content


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
            await fetch_file_content(
                client, "owner", "repo", "file.py", "abc123", "ghp_token"
            )

    assert exc_info.value.response.status_code == 500
