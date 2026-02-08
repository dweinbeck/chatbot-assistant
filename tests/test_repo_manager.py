"""Tests for the repo manager service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.repo_manager import get_or_create_repo


@pytest.mark.anyio
async def test_get_or_create_repo_existing():
    """Returns existing Repo without creating a new one."""
    existing_repo = MagicMock()
    existing_repo.id = 123

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing_repo

    session = AsyncMock()
    session.execute.return_value = result_mock
    session.add = MagicMock()

    repo = await get_or_create_repo(session, 123, "owner", "repo")

    assert repo is existing_repo
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


@pytest.mark.anyio
async def test_get_or_create_repo_creates_new():
    """Creates and flushes a new Repo when none exists."""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None

    session = AsyncMock()
    session.execute.return_value = result_mock
    session.add = MagicMock()

    repo = await get_or_create_repo(session, 456, "dweinbeck", "my-repo")

    assert repo.id == 456
    assert repo.owner == "dweinbeck"
    assert repo.name == "my-repo"
    session.add.assert_called_once()
    session.flush.assert_awaited_once()
