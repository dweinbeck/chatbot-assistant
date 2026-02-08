"""Integration tests for the /healthz endpoint using a mocked DB session."""

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_healthz_returns_200(client: AsyncClient) -> None:
    """GET /healthz should return 200 with status and database keys."""
    response = await client.get("/healthz")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"


@pytest.mark.anyio
async def test_healthz_response_keys(client: AsyncClient) -> None:
    """GET /healthz response should contain exactly the expected keys."""
    response = await client.get("/healthz")
    body = response.json()
    assert set(body.keys()) == {"status", "database"}
