"""Integration tests for the /health endpoint using a mocked DB session."""

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_health_returns_200(client: AsyncClient) -> None:
    """GET /health should return 200 with status and database keys."""
    response = await client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"


@pytest.mark.anyio
async def test_health_response_keys(client: AsyncClient) -> None:
    """GET /health response should contain exactly the expected keys."""
    response = await client.get("/health")
    body = response.json()
    assert set(body.keys()) == {"status", "database"}
