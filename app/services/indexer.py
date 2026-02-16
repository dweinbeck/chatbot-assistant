"""Indexer orchestration service for the file ingestion pipeline.

Coordinates the full indexing flow: denylist check -> content fetch ->
hash comparison -> chunking -> database upsert. Handles both new files
and updates to existing files, as well as file deletion.
"""

import hashlib

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KBChunk, KBFile
from app.services.chunker import chunk_file
from app.services.denylist import is_denied
from app.services.github_client import fetch_file_content
from app.services.repo_manager import get_or_create_repo

logger = structlog.get_logger()


async def index_file(
    session: AsyncSession,
    github_client: object,
    owner: str,
    repo: str,
    repo_id: int,
    path: str,
    commit_sha: str,
    token: str,
) -> dict:
    """Orchestrate the full indexing flow for a single file.

    Steps:
    1. Check denylist by path pattern
    2. Fetch content from GitHub at the given commit SHA
    3. Check denylist by file size
    4. Compute sha256 hash and compare with existing record
    5. Skip, update, or create file + chunk records accordingly

    Args:
        session: Async database session for DB operations.
        github_client: httpx.AsyncClient instance for GitHub API calls.
        owner: Repository owner (user or organisation).
        repo: Repository name.
        repo_id: Database ID of the repository.
        path: File path within the repository.
        commit_sha: Git commit SHA to fetch content at.
        token: GitHub personal access token or installation token.

    Returns:
        Dict with status key indicating the outcome:
        - {"status": "skipped", "reason": "denylist"} if path is denied
        - {"status": "skipped", "reason": "not_found"} if file not found on GitHub
        - {"status": "skipped", "reason": "size"} if file exceeds size limit
        - {"status": "unchanged"} if content hash matches existing record
        - {"status": "indexed", "chunks": N} on successful indexing
    """
    # Step 0: Ensure Repo row exists (FK integrity)
    # Use the returned repo's actual ID for all FK references, since the
    # repo may have been created earlier with a different ID (e.g. synthetic
    # ID from ingest-url vs real GitHub ID from sync-repo).
    repo_row = await get_or_create_repo(session, repo_id, owner, repo)
    actual_repo_id = repo_row.id

    # Step 1: Check denylist by path pattern
    if is_denied(path):
        logger.debug("skipping_denied_path", path=path)
        return {"status": "skipped", "reason": "denylist"}

    # Step 2: Fetch content from GitHub
    content = await fetch_file_content(github_client, owner, repo, path, commit_sha, token)
    if content is None:
        logger.debug("file_not_found", path=path, commit_sha=commit_sha)
        return {"status": "skipped", "reason": "not_found"}

    # Step 3: Check denylist by file size
    size_bytes = len(content.encode("utf-8"))
    if is_denied(path, size_bytes=size_bytes):
        logger.debug("skipping_oversized_file", path=path, size_bytes=size_bytes)
        return {"status": "skipped", "reason": "size"}

    # Step 4: Compute content hash
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # Step 5: Query existing KBFile by repo_id + path
    result = await session.execute(
        select(KBFile).where(KBFile.repo_id == actual_repo_id, KBFile.path == path)
    )
    existing_file = result.scalar_one_or_none()

    if existing_file is not None:
        if existing_file.sha256 == content_hash:
            # Content unchanged -- just update the commit_sha
            existing_file.commit_sha = commit_sha
            return {"status": "unchanged"}

        # Content changed -- delete old chunks and update file record
        await session.execute(delete(KBChunk).where(KBChunk.file_id == existing_file.id))
        existing_file.sha256 = content_hash
        existing_file.commit_sha = commit_sha
        kb_file = existing_file
    else:
        # New file -- create KBFile record
        kb_file = KBFile(
            repo_id=actual_repo_id,
            path=path,
            commit_sha=commit_sha,
            sha256=content_hash,
        )
        session.add(kb_file)
        await session.flush()  # Get the generated ID

    # Step 6: Chunk the content
    chunks = chunk_file(content, path)

    # Step 7: Create KBChunk records
    for start_line, end_line, chunk_content in chunks:
        chunk = KBChunk(
            repo_id=actual_repo_id,
            file_id=kb_file.id,
            path=path,
            commit_sha=commit_sha,
            start_line=start_line,
            end_line=end_line,
            content=chunk_content,
        )
        session.add(chunk)

    logger.info("file_indexed", path=path, chunks=len(chunks))
    return {"status": "indexed", "chunks": len(chunks)}


async def delete_file(session: AsyncSession, repo_id: int, path: str) -> dict:
    """Delete a file and its chunks from the knowledge base.

    Args:
        session: Async database session for DB operations.
        repo_id: Database ID of the repository.
        path: File path within the repository.

    Returns:
        Dict with status key:
        - {"status": "deleted"} on successful deletion
        - {"status": "not_found"} if the file does not exist
    """
    result = await session.execute(
        select(KBFile).where(KBFile.repo_id == repo_id, KBFile.path == path)
    )
    existing_file = result.scalar_one_or_none()

    if existing_file is None:
        return {"status": "not_found"}

    # Delete chunks first, then the file
    await session.execute(delete(KBChunk).where(KBChunk.file_id == existing_file.id))
    await session.delete(existing_file)

    logger.info("file_deleted", path=path, repo_id=repo_id)
    return {"status": "deleted"}
