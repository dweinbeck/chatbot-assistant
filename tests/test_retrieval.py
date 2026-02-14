"""Tests for the FTS + trigram retrieval service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retrieval import (
    RetrievedChunk,
    _build_or_tsquery_text,
    has_any_chunks,
    retrieve_chunks,
    search_fts,
    search_fts_or,
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
# _build_or_tsquery_text tests
# ---------------------------------------------------------------------------


def test_build_or_tsquery_text_basic() -> None:
    """Joins words with OR operator."""
    result = _build_or_tsquery_text("How does the chatbot work")
    assert result == "How | does | the | chatbot | work"


def test_build_or_tsquery_text_deduplicates() -> None:
    """Duplicate words are removed, first occurrence order preserved."""
    assert _build_or_tsquery_text("foo bar foo baz bar") == "foo | bar | baz"


def test_build_or_tsquery_text_special_chars() -> None:
    """Non-alphanumeric characters are stripped; only words remain."""
    assert _build_or_tsquery_text("hello! @world #test") == "hello | world | test"


def test_build_or_tsquery_text_empty() -> None:
    """Returns None for empty or all-punctuation input."""
    assert _build_or_tsquery_text("") is None
    assert _build_or_tsquery_text("!@#$%") is None


# ---------------------------------------------------------------------------
# search_fts_or tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_fts_or_returns_results(mock_db_session: AsyncMock) -> None:
    """OR-based FTS returns chunks when any term matches."""
    rows = [
        _make_row(1, "acme", "repo", "src/a.py", "aaa", 1, 10, "def chatbot():", 0.5),
        _make_row(2, "acme", "repo", "src/b.py", "bbb", 5, 20, "class Backend:", 0.3),
    ]
    mock_db_session.execute.return_value = iter(rows)

    results = await search_fts_or(mock_db_session, "chatbot backend work")

    assert len(results) == 2
    assert results[0].score == 0.5
    assert results[1].score == 0.3


@pytest.mark.anyio
async def test_search_fts_or_empty_results(mock_db_session: AsyncMock) -> None:
    """OR-based FTS returns empty list when no terms match."""
    mock_db_session.execute.return_value = iter([])

    results = await search_fts_or(mock_db_session, "xyznonexistent")

    assert results == []


@pytest.mark.anyio
async def test_search_fts_or_no_valid_terms() -> None:
    """OR-based FTS returns empty list when query has no valid words."""
    session = AsyncMock()

    results = await search_fts_or(session, "!@#$%")

    assert results == []
    session.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# has_any_chunks tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_has_any_chunks_true(mock_db_session: AsyncMock) -> None:
    """Returns True when kb_chunks has at least one row."""
    mock_result = MagicMock()
    mock_result.first.return_value = MagicMock()  # non-None row
    mock_db_session.execute.return_value = mock_result

    assert await has_any_chunks(mock_db_session) is True


@pytest.mark.anyio
async def test_has_any_chunks_false(mock_db_session: AsyncMock) -> None:
    """Returns False when kb_chunks is empty."""
    mock_result = MagicMock()
    mock_result.first.return_value = None
    mock_db_session.execute.return_value = mock_result

    assert await has_any_chunks(mock_db_session) is False


# ---------------------------------------------------------------------------
# Higher-level tests (retrieve_chunks -- patch search_fts / search_trigram)
# ---------------------------------------------------------------------------

_MODULE = "app.services.retrieval"


@pytest.mark.anyio
async def test_retrieve_chunks_fts_sufficient() -> None:
    """When FTS-AND returns >= min_fts_results, OR fallback and trigram are NOT called."""
    fts_chunks = [_make_chunk(i, score=1.0 - i * 0.1) for i in range(5)]

    with (
        patch(f"{_MODULE}.search_fts", new_callable=AsyncMock) as mock_fts,
        patch(f"{_MODULE}.search_fts_or", new_callable=AsyncMock) as mock_fts_or,
        patch(f"{_MODULE}.search_trigram", new_callable=AsyncMock) as mock_tri,
    ):
        mock_fts.return_value = fts_chunks
        session = AsyncMock()

        results = await retrieve_chunks(session, "query", min_fts_results=3)

    assert len(results) == 5
    mock_fts.assert_awaited_once()
    mock_fts_or.assert_not_awaited()
    mock_tri.assert_not_awaited()


@pytest.mark.anyio
async def test_retrieve_chunks_triggers_trigram_fallback() -> None:
    """When FTS-AND returns < min_fts_results (but > 0), trigram fallback is called."""
    fts_chunks = [_make_chunk(1, score=0.9)]
    tri_chunks = [
        _make_chunk(10, score=0.7),
        _make_chunk(11, score=0.5),
        _make_chunk(12, score=0.3),
    ]

    with (
        patch(f"{_MODULE}.search_fts", new_callable=AsyncMock) as mock_fts,
        patch(f"{_MODULE}.search_fts_or", new_callable=AsyncMock) as mock_fts_or,
        patch(f"{_MODULE}.search_trigram", new_callable=AsyncMock) as mock_tri,
    ):
        mock_fts.return_value = fts_chunks
        mock_tri.return_value = tri_chunks
        session = AsyncMock()

        results = await retrieve_chunks(session, "query", min_fts_results=3)

    assert len(results) == 4
    mock_fts.assert_awaited_once()
    # OR fallback NOT called because AND returned 1 result (> 0)
    mock_fts_or.assert_not_awaited()
    mock_tri.assert_awaited_once()
    # FTS results come first
    assert results[0].id == 1
    assert results[1].id == 10


@pytest.mark.anyio
async def test_retrieve_chunks_or_fallback_when_and_empty() -> None:
    """When FTS-AND returns 0 results, OR fallback fires before trigram."""
    or_chunks = [
        _make_chunk(20, score=0.4),
        _make_chunk(21, score=0.3),
        _make_chunk(22, score=0.2),
    ]

    with (
        patch(f"{_MODULE}.search_fts", new_callable=AsyncMock) as mock_fts,
        patch(f"{_MODULE}.search_fts_or", new_callable=AsyncMock) as mock_fts_or,
        patch(f"{_MODULE}.search_trigram", new_callable=AsyncMock) as mock_tri,
    ):
        mock_fts.return_value = []
        mock_fts_or.return_value = or_chunks
        session = AsyncMock()

        results = await retrieve_chunks(session, "chatbot backend work", min_fts_results=3)

    assert len(results) == 3
    mock_fts.assert_awaited_once()
    mock_fts_or.assert_awaited_once()
    # OR returned enough — trigram NOT called
    mock_tri.assert_not_awaited()
    assert results[0].id == 20


@pytest.mark.anyio
async def test_retrieve_chunks_or_fallback_insufficient_triggers_trigram() -> None:
    """When FTS-AND empty and OR returns < min_fts, trigram also fires."""
    or_chunks = [_make_chunk(20, score=0.4)]
    tri_chunks = [_make_chunk(30, score=0.2), _make_chunk(31, score=0.15)]

    with (
        patch(f"{_MODULE}.search_fts", new_callable=AsyncMock) as mock_fts,
        patch(f"{_MODULE}.search_fts_or", new_callable=AsyncMock) as mock_fts_or,
        patch(f"{_MODULE}.search_trigram", new_callable=AsyncMock) as mock_tri,
    ):
        mock_fts.return_value = []
        mock_fts_or.return_value = or_chunks
        mock_tri.return_value = tri_chunks
        session = AsyncMock()

        results = await retrieve_chunks(session, "query", min_fts_results=3)

    assert len(results) == 3
    mock_fts.assert_awaited_once()
    mock_fts_or.assert_awaited_once()
    mock_tri.assert_awaited_once()
    assert results[0].id == 20
    assert results[1].id == 30


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
        patch(f"{_MODULE}.search_fts_or", new_callable=AsyncMock),
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
        patch(f"{_MODULE}.search_fts_or", new_callable=AsyncMock),
        patch(f"{_MODULE}.search_trigram", new_callable=AsyncMock) as mock_tri,
    ):
        mock_fts.return_value = fts_chunks
        mock_tri.return_value = tri_chunks
        session = AsyncMock()

        results = await retrieve_chunks(session, "query", min_fts_results=3, max_chunks=12)

    assert len(results) == 12
