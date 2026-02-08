"""Tests for the FTS + trigram retrieval service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retrieval import (
    RetrievedChunk,
    retrieve_chunks,
    search_fts,
    search_trigram,
)


def _make_row(
    chunk_id: int,
    owner: str,
    name: str,
    path: str,
    sha: str,
    start: int,
    end: int,
    content: str,
    score: float,
) -> MagicMock:
    """Build a mock row that mimics a SQLAlchemy result row with attribute access."""
    row = MagicMock()
    row.id = chunk_id
    row.owner = owner
    row.name = name
    row.path = path
    row.commit_sha = sha
    row.start_line = start
    row.end_line = end
    row.content = content
    row.rank = score
    row.similarity = score
    return row


def _make_chunk(
    chunk_id: int,
    score: float = 0.5,
    owner: str = "acme",
    name: str = "repo",
) -> RetrievedChunk:
    """Build a RetrievedChunk for higher-level function tests."""
    return RetrievedChunk(
        id=chunk_id,
        repo_owner=owner,
        repo_name=name,
        path=f"src/file_{chunk_id}.py",
        commit_sha="abc1234",
        start_line=1,
        end_line=10,
        content=f"content_{chunk_id}",
        score=score,
    )


# ---------------------------------------------------------------------------
# Direct DB-mock tests (search_fts, search_trigram)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_fts_returns_ranked_results(mock_db_session: AsyncMock) -> None:
    """FTS returns RetrievedChunk objects ordered by score descending."""
    rows = [
        _make_row(1, "acme", "repo", "src/a.py", "aaa", 1, 10, "def foo():", 0.9),
        _make_row(2, "acme", "repo", "src/b.py", "bbb", 5, 20, "class Bar:", 0.6),
        _make_row(3, "acme", "repo", "src/c.py", "ccc", 1, 5, "import os", 0.3),
    ]
    mock_db_session.execute.return_value = iter(rows)

    results = await search_fts(mock_db_session, "foo bar")

    assert len(results) == 3
    assert all(isinstance(r, RetrievedChunk) for r in results)
    # Scores should match the rank values from the rows
    assert results[0].score == 0.9
    assert results[1].score == 0.6
    assert results[2].score == 0.3
    # Verify all fields populated
    chunk = results[0]
    assert chunk.repo_owner == "acme"
    assert chunk.repo_name == "repo"
    assert chunk.path == "src/a.py"
    assert chunk.commit_sha == "aaa"
    assert chunk.start_line == 1
    assert chunk.end_line == 10
    assert chunk.content == "def foo():"


@pytest.mark.anyio
async def test_search_fts_empty_results(mock_db_session: AsyncMock) -> None:
    """FTS returns an empty list when no documents match."""
    mock_db_session.execute.return_value = iter([])

    results = await search_fts(mock_db_session, "nonexistent_term")

    assert results == []


@pytest.mark.anyio
async def test_search_trigram_returns_similar_paths(
    mock_db_session: AsyncMock,
) -> None:
    """Trigram search returns RetrievedChunk objects with similarity scores."""
    rows = [
        _make_row(10, "acme", "repo", "src/config.py", "ddd", 1, 30, "# config", 0.8),
        _make_row(11, "acme", "repo", "src/conf.py", "eee", 1, 15, "# conf", 0.5),
    ]
    mock_db_session.execute.return_value = iter(rows)

    results = await search_trigram(mock_db_session, "config.py")

    assert len(results) == 2
    assert results[0].score == 0.8
    assert results[1].score == 0.5
    assert results[0].path == "src/config.py"


# ---------------------------------------------------------------------------
# Higher-level tests (retrieve_chunks -- patch search_fts / search_trigram)
# ---------------------------------------------------------------------------

_MODULE = "app.services.retrieval"


@pytest.mark.anyio
async def test_retrieve_chunks_fts_sufficient() -> None:
    """When FTS returns >= min_fts_results, trigram is NOT called."""
    fts_chunks = [_make_chunk(i, score=1.0 - i * 0.1) for i in range(5)]

    with (
        patch(f"{_MODULE}.search_fts", new_callable=AsyncMock) as mock_fts,
        patch(f"{_MODULE}.search_trigram", new_callable=AsyncMock) as mock_tri,
    ):
        mock_fts.return_value = fts_chunks
        session = AsyncMock()

        results = await retrieve_chunks(session, "query", min_fts_results=3)

    assert len(results) == 5
    mock_fts.assert_awaited_once()
    mock_tri.assert_not_awaited()


@pytest.mark.anyio
async def test_retrieve_chunks_triggers_trigram_fallback() -> None:
    """When FTS returns < min_fts_results, trigram fallback is called and merged."""
    fts_chunks = [_make_chunk(1, score=0.9)]
    tri_chunks = [
        _make_chunk(10, score=0.7),
        _make_chunk(11, score=0.5),
        _make_chunk(12, score=0.3),
    ]

    with (
        patch(f"{_MODULE}.search_fts", new_callable=AsyncMock) as mock_fts,
        patch(f"{_MODULE}.search_trigram", new_callable=AsyncMock) as mock_tri,
    ):
        mock_fts.return_value = fts_chunks
        mock_tri.return_value = tri_chunks
        session = AsyncMock()

        results = await retrieve_chunks(session, "query", min_fts_results=3)

    assert len(results) == 4
    mock_fts.assert_awaited_once()
    mock_tri.assert_awaited_once()
    # FTS results come first
    assert results[0].id == 1
    assert results[1].id == 10


@pytest.mark.anyio
async def test_retrieve_chunks_deduplicates() -> None:
    """Duplicate chunk ids from trigram are excluded."""
    fts_chunks = [_make_chunk(1, score=0.9), _make_chunk(2, score=0.8)]
    tri_chunks = [
        _make_chunk(2, score=0.7),  # duplicate of FTS id=2
        _make_chunk(3, score=0.6),
        _make_chunk(4, score=0.5),
    ]

    with (
        patch(f"{_MODULE}.search_fts", new_callable=AsyncMock) as mock_fts,
        patch(f"{_MODULE}.search_trigram", new_callable=AsyncMock) as mock_tri,
    ):
        mock_fts.return_value = fts_chunks
        mock_tri.return_value = tri_chunks
        session = AsyncMock()

        results = await retrieve_chunks(session, "query", min_fts_results=3)

    ids = [r.id for r in results]
    assert ids == [1, 2, 3, 4]  # no duplicate id=2
    assert len(results) == 4


@pytest.mark.anyio
async def test_retrieve_chunks_respects_max_chunks() -> None:
    """Combined results are capped at max_chunks."""
    fts_chunks = [_make_chunk(1), _make_chunk(2)]
    tri_chunks = [_make_chunk(i + 10) for i in range(15)]

    with (
        patch(f"{_MODULE}.search_fts", new_callable=AsyncMock) as mock_fts,
        patch(f"{_MODULE}.search_trigram", new_callable=AsyncMock) as mock_tri,
    ):
        mock_fts.return_value = fts_chunks
        mock_tri.return_value = tri_chunks
        session = AsyncMock()

        results = await retrieve_chunks(
            session, "query", min_fts_results=3, max_chunks=12
        )

    assert len(results) == 12
