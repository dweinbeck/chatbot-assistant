"""Retrieval service: FTS search with ts_rank_cd ranking and trigram similarity fallback.

Retrieves relevant code chunks from the knowledge base given a user's question.
Uses PostgreSQL full-text search as the primary strategy and pg_trgm similarity
on file paths as a fallback when FTS returns too few results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select, text

from app.db.models import KBChunk, KBFile, Repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class RetrievedChunk:
    """A retrieved chunk with all fields needed for citation building.

    Citation format: ``repo_owner/repo_name/path@commit_sha:start_line-end_line``
    """

    id: int
    repo_owner: str
    repo_name: str
    path: str
    commit_sha: str
    start_line: int
    end_line: int
    content: str
    score: float


async def search_fts(
    session: AsyncSession,
    query: str,
    limit: int = 12,
) -> list[RetrievedChunk]:
    """Full-text search using websearch_to_tsquery with ts_rank_cd ranking.

    Uses ``websearch_to_tsquery`` (never ``to_tsquery``) to safely parse user
    input without syntax errors.  Results are ranked by cover density
    (``ts_rank_cd``), which considers term proximity -- ideal for code where
    related terms cluster together.

    Args:
        session: Async SQLAlchemy session.
        query: User's search query (plain text).
        limit: Maximum number of chunks to return.

    Returns:
        List of RetrievedChunk ordered by ts_rank_cd score descending.
    """
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank_cd(KBChunk.content_tsv, tsquery)

    stmt = (
        select(
            KBChunk.id,
            Repo.owner,
            Repo.name,
            KBChunk.path,
            KBChunk.commit_sha,
            KBChunk.start_line,
            KBChunk.end_line,
            KBChunk.content,
            rank.label("rank"),
        )
        .join(Repo, KBChunk.repo_id == Repo.id)
        .where(KBChunk.content_tsv.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(limit)
    )

    result = await session.execute(stmt)
    return [
        RetrievedChunk(
            id=row.id,
            repo_owner=row.owner,
            repo_name=row.name,
            path=row.path,
            commit_sha=row.commit_sha,
            start_line=row.start_line,
            end_line=row.end_line,
            content=row.content,
            score=row.rank,
        )
        for row in result
    ]


async def search_trigram(
    session: AsyncSession,
    query: str,
    limit: int = 12,
    threshold: float = 0.15,
) -> list[RetrievedChunk]:
    """Trigram similarity search on file path for symbol/filename queries.

    JOINs KBChunk with KBFile to compute similarity on ``KBFile.path``, which
    has the ``ix_kb_files_path_trgm`` GIN index.  Using ``KBChunk.path``
    directly would bypass the index and cause a full table scan.

    Uses an explicit threshold (default 0.15) rather than the ``%`` operator,
    which depends on the ``pg_trgm.similarity_threshold`` GUC variable.

    Args:
        session: Async SQLAlchemy session.
        query: User's search query (plain text, often a filename or symbol).
        limit: Maximum number of chunks to return.
        threshold: Minimum similarity score to include a result.

    Returns:
        List of RetrievedChunk ordered by similarity score descending.
    """
    similarity = func.similarity(KBFile.path, query)

    stmt = (
        select(
            KBChunk.id,
            Repo.owner,
            Repo.name,
            KBChunk.path,
            KBChunk.commit_sha,
            KBChunk.start_line,
            KBChunk.end_line,
            KBChunk.content,
            similarity.label("similarity"),
        )
        .join(KBFile, KBChunk.file_id == KBFile.id)
        .join(Repo, KBChunk.repo_id == Repo.id)
        .where(similarity > threshold)
        .order_by(similarity.desc())
        .limit(limit)
    )

    result = await session.execute(stmt)
    return [
        RetrievedChunk(
            id=row.id,
            repo_owner=row.owner,
            repo_name=row.name,
            path=row.path,
            commit_sha=row.commit_sha,
            start_line=row.start_line,
            end_line=row.end_line,
            content=row.content,
            score=row.similarity,
        )
        for row in result
    ]


_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")


def _build_or_tsquery_text(query: str) -> str | None:
    """Extract unique words from *query* and join with OR (``|``) for tsquery.

    Returns ``None`` when no valid words remain (e.g. empty or all-punctuation).
    Input is sanitised to ``[a-zA-Z0-9_]`` only, so the result is safe for
    ``to_tsquery``.
    """
    words = list(dict.fromkeys(_WORD_RE.findall(query)))  # deduplicate, keep order
    if not words:
        return None
    return " | ".join(words)


async def search_fts_or(
    session: AsyncSession,
    query: str,
    limit: int = 12,
) -> list[RetrievedChunk]:
    """OR-based full-text search fallback.

    Fires when the AND-based ``search_fts`` returns zero results.  Extracts
    individual words from the query and joins them with ``|`` (OR) so that
    chunks matching *any* term are returned.  Uses ``to_tsquery`` (safe because
    ``_build_or_tsquery_text`` guarantees only alphanumeric words joined by
    ``|``).
    """
    or_text = _build_or_tsquery_text(query)
    if or_text is None:
        return []

    tsquery = func.to_tsquery("english", or_text)
    rank = func.ts_rank_cd(KBChunk.content_tsv, tsquery)

    stmt = (
        select(
            KBChunk.id,
            Repo.owner,
            Repo.name,
            KBChunk.path,
            KBChunk.commit_sha,
            KBChunk.start_line,
            KBChunk.end_line,
            KBChunk.content,
            rank.label("rank"),
        )
        .join(Repo, KBChunk.repo_id == Repo.id)
        .where(KBChunk.content_tsv.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(limit)
    )

    result = await session.execute(stmt)
    return [
        RetrievedChunk(
            id=row.id,
            repo_owner=row.owner,
            repo_name=row.name,
            path=row.path,
            commit_sha=row.commit_sha,
            start_line=row.start_line,
            end_line=row.end_line,
            content=row.content,
            score=row.rank,
        )
        for row in result
    ]


async def has_any_chunks(session: AsyncSession) -> bool:
    """Return True if the kb_chunks table has at least one row."""
    result = await session.execute(text("SELECT id FROM kb_chunks LIMIT 1"))
    return result.first() is not None


async def retrieve_chunks(
    session: AsyncSession,
    query: str,
    min_fts_results: int = 3,
    max_chunks: int = 12,
) -> list[RetrievedChunk]:
    """Retrieve chunks: FTS-AND first, then OR fallback, then trigram.

    1. Run full-text search with ``websearch_to_tsquery`` (AND semantics).
    2. If FTS-AND returns **zero** results, try OR-based FTS fallback.
    3. If still fewer than *min_fts_results*, also run trigram similarity.
    4. Merge results (deduplicated by chunk id), cap at *max_chunks*.

    Args:
        session: Async SQLAlchemy session.
        query: User's search query (plain text).
        min_fts_results: Trigger trigram fallback when FTS returns fewer than this.
        max_chunks: Maximum total chunks to return.

    Returns:
        List of RetrievedChunk, FTS results first then trigram, capped at max_chunks.
    """
    results = await search_fts(session, query, limit=max_chunks)

    # OR fallback: only when AND returned zero results
    if len(results) == 0:
        results = await search_fts_or(session, query, limit=max_chunks)

    if len(results) < min_fts_results:
        trigram_results = await search_trigram(session, query, limit=max_chunks)
        seen_ids = {chunk.id for chunk in results}
        for chunk in trigram_results:
            if chunk.id not in seen_ids and len(results) < max_chunks:
                results.append(chunk)
                seen_ids.add(chunk.id)

    return results[:max_chunks]
