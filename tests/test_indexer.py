"""Tests for the indexer orchestration service.

Each test isolates the indexer logic by mocking external dependencies:
denylist, GitHub client, chunker, and the database session.
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.indexer import delete_file, index_file

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_session(existing_file=None):
    """Build a mock AsyncSession.

    If existing_file is provided, session.execute().scalar_one_or_none()
    returns that object. Otherwise returns None (no existing file).
    Sync methods like ``add`` use MagicMock to avoid coroutine warnings.
    """
    session = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = existing_file
    session.execute.return_value = result_mock
    # session.add is synchronous in SQLAlchemy, so use a plain MagicMock
    session.add = MagicMock()
    return session


def _make_kb_file(*, file_id=1, repo_id=1, path="src/main.py", commit_sha="aaa", sha256="abc123"):
    """Create a fake KBFile-like object for testing."""
    obj = MagicMock()
    obj.id = file_id
    obj.repo_id = repo_id
    obj.path = path
    obj.commit_sha = commit_sha
    obj.sha256 = sha256
    return obj


# ---------------------------------------------------------------------------
# index_file tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@patch("app.services.indexer.fetch_file_content", new_callable=AsyncMock)
@patch("app.services.indexer.is_denied", return_value=True)
async def test_index_file_denylist_skip(mock_denied, mock_fetch):
    """Path matching denylist returns skipped status without GitHub API call."""
    session = _mock_session()
    client = AsyncMock()

    result = await index_file(
        session, client, "owner", "repo", 1, "node_modules/foo.js", "sha1", "tok",
    )

    assert result == {"status": "skipped", "reason": "denylist"}
    mock_fetch.assert_not_called()
    session.add.assert_not_called()


@pytest.mark.anyio
@patch("app.services.indexer.chunk_file")
@patch("app.services.indexer.fetch_file_content", new_callable=AsyncMock, return_value=None)
@patch("app.services.indexer.is_denied", return_value=False)
async def test_index_file_not_found(mock_denied, mock_fetch, mock_chunk):
    """GitHub returning None (404) results in skipped/not_found status."""
    session = _mock_session()
    client = AsyncMock()

    result = await index_file(session, client, "owner", "repo", 1, "gone.py", "sha1", "tok")

    assert result == {"status": "skipped", "reason": "not_found"}
    mock_chunk.assert_not_called()


@pytest.mark.anyio
@patch("app.services.indexer.chunk_file", return_value=[(1, 10, "chunk content")])
@patch(
    "app.services.indexer.fetch_file_content",
    new_callable=AsyncMock,
    return_value="print('hello')",
)
@patch("app.services.indexer.is_denied", return_value=False)
async def test_index_file_new_file(mock_denied, mock_fetch, mock_chunk):
    """Happy path: new file is fetched, chunked, and KBFile + KBChunks created."""
    session = _mock_session(existing_file=None)
    client = AsyncMock()

    result = await index_file(session, client, "owner", "repo", 1, "src/main.py", "sha1", "tok")

    assert result["status"] == "indexed"
    assert result["chunks"] == 1
    # KBFile added via session.add (at least 2 calls: 1 for file, 1 for chunk)
    assert session.add.call_count >= 2
    session.flush.assert_awaited_once()


@pytest.mark.anyio
@patch("app.services.indexer.chunk_file")
@patch("app.services.indexer.fetch_file_content", new_callable=AsyncMock)
@patch("app.services.indexer.is_denied", return_value=False)
async def test_index_file_unchanged(mock_denied, mock_fetch, mock_chunk):
    """Existing file with same sha256 returns unchanged and skips chunking."""
    content = "print('hello')"
    mock_fetch.return_value = content

    content_hash = hashlib.sha256(content.encode()).hexdigest()
    existing = _make_kb_file(sha256=content_hash)

    session = _mock_session(existing_file=existing)
    client = AsyncMock()

    result = await index_file(session, client, "owner", "repo", 1, "src/main.py", "newsha", "tok")

    assert result == {"status": "unchanged"}
    # commit_sha should be updated
    assert existing.commit_sha == "newsha"
    # No chunking should happen
    mock_chunk.assert_not_called()


@pytest.mark.anyio
@patch("app.services.indexer.chunk_file", return_value=[(1, 5, "new chunk")])
@patch(
    "app.services.indexer.fetch_file_content",
    new_callable=AsyncMock,
    return_value="updated content",
)
@patch("app.services.indexer.is_denied", return_value=False)
async def test_index_file_updated(mock_denied, mock_fetch, mock_chunk):
    """Existing file with different sha256: old chunks deleted, new chunks created."""
    existing = _make_kb_file(sha256="old_hash")
    session = _mock_session(existing_file=existing)
    client = AsyncMock()

    result = await index_file(session, client, "owner", "repo", 1, "src/main.py", "newsha", "tok")

    assert result["status"] == "indexed"
    assert result["chunks"] == 1
    # session.execute should have been called for select AND delete
    assert session.execute.call_count >= 2
    # sha256 and commit_sha should be updated on the existing file
    expected_hash = hashlib.sha256(b"updated content").hexdigest()
    assert existing.sha256 == expected_hash
    assert existing.commit_sha == "newsha"


# ---------------------------------------------------------------------------
# delete_file tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_delete_file_exists():
    """Existing file and its chunks are deleted, returns deleted status."""
    existing = _make_kb_file()
    session = _mock_session(existing_file=existing)

    result = await delete_file(session, 1, "src/main.py")

    assert result == {"status": "deleted"}
    # Should have executed delete for chunks
    assert session.execute.call_count >= 2
    session.delete.assert_awaited_once_with(existing)


@pytest.mark.anyio
async def test_delete_file_not_found():
    """Non-existent file returns not_found status."""
    session = _mock_session(existing_file=None)

    result = await delete_file(session, 1, "nonexistent.py")

    assert result == {"status": "not_found"}
    session.delete.assert_not_called()
