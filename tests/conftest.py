"""Shared test fixtures for async DB session and FastAPI test client."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.dependencies import get_task_queue
from app.main import app
from app.services.task_queue import InMemoryTaskQueue


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """Create a mock async database session.

    The mock's execute method returns successfully, simulating a healthy DB.
    """
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = None
    return session


@pytest.fixture
def mock_task_queue() -> InMemoryTaskQueue:
    """Create a fresh in-memory task queue for test inspection."""
    return InMemoryTaskQueue()


@pytest.fixture
async def client(
    mock_db_session: AsyncMock,
    mock_task_queue: InMemoryTaskQueue,
) -> AsyncGenerator[AsyncClient, None]:
    """Yield an httpx AsyncClient with dependencies overridden.

    Uses the mock session so tests don't require a running database,
    and an in-memory task queue for inspecting enqueued tasks.
    """

    async def _override_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db_session  # type: ignore[misc]

    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_task_queue] = lambda: mock_task_queue
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
