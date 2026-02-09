"""Admin router for seeding the knowledge base.

Provides endpoints to sync public GitHub repos and ingest web page content
for private repos that cannot be accessed via the GitHub API.
"""

import hashlib
from html.parser import HTMLParser
from typing import Annotated
from urllib.parse import urlparse

import httpx
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import KBChunk, KBFile
from app.db.session import get_db_session
from app.dependencies import get_task_queue
from app.schemas.admin import (
    BackfillRepoResult,
    BackfillRequest,
    BackfillResponse,
    IngestURLRequest,
    IngestURLResponse,
    SyncRepoRequest,
    SyncRepoResponse,
)
from app.schemas.tasks import IndexFilePayload
from app.services.chunker import chunk_file
from app.services.denylist import is_denied
from app.services.github_client import get_repo_metadata, list_repo_files
from app.services.repo_manager import get_or_create_repo
from app.services.task_queue import TaskQueue

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text extractor using stdlib html.parser."""

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._skip = False
        self._skip_tags = {"script", "style", "noscript"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._pieces.append(stripped)

    def get_text(self) -> str:
        return "\n".join(self._pieces)


def extract_text_from_html(html: str) -> str:
    """Extract visible text from HTML, stripping script/style tags."""
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


@router.post("/sync-repo")
async def sync_repo(
    request: SyncRepoRequest,
    task_queue: Annotated[TaskQueue, Depends(get_task_queue)],
) -> SyncRepoResponse:
    """Sync a public GitHub repo by listing all files and enqueuing index tasks."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        meta = await get_repo_metadata(client, request.owner, request.repo, settings.github_token)
        repo_id: int = meta["id"]

        files = await list_repo_files(
            client, request.owner, request.repo, request.ref, settings.github_token
        )

    base_url = settings.task_handler_base_url
    tasks_enqueued = 0
    files_skipped = 0

    for path in files:
        if is_denied(path):
            files_skipped += 1
            continue

        payload = IndexFilePayload(
            repo_owner=request.owner,
            repo_name=request.repo,
            repo_id=repo_id,
            path=path,
            commit_sha=request.ref,
        )
        await task_queue.enqueue(
            f"{base_url}/tasks/index-file",
            payload.model_dump(),
        )
        tasks_enqueued += 1

    logger.info(
        "sync_repo_complete",
        owner=request.owner,
        repo=request.repo,
        files_found=len(files),
        tasks_enqueued=tasks_enqueued,
        files_skipped=files_skipped,
    )

    return SyncRepoResponse(
        status="accepted",
        repo_id=repo_id,
        files_found=len(files),
        tasks_enqueued=tasks_enqueued,
        files_skipped_denylist=files_skipped,
    )


@router.post("/backfill")
async def backfill(
    request: BackfillRequest,
    task_queue: Annotated[TaskQueue, Depends(get_task_queue)],
) -> BackfillResponse:
    """Backfill multiple repos at once by listing files and enqueuing index tasks."""
    results: list[BackfillRepoResult] = []
    total_enqueued = 0

    for item in request.repos:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                meta = await get_repo_metadata(
                    client, item.owner, item.repo, settings.github_token
                )
                repo_id: int = meta["id"]
                files = await list_repo_files(
                    client, item.owner, item.repo, item.ref, settings.github_token
                )

            base_url = settings.task_handler_base_url
            tasks_enqueued = 0
            files_skipped = 0

            for path in files:
                if is_denied(path):
                    files_skipped += 1
                    continue

                payload = IndexFilePayload(
                    repo_owner=item.owner,
                    repo_name=item.repo,
                    repo_id=repo_id,
                    path=path,
                    commit_sha=item.ref,
                )
                await task_queue.enqueue(
                    f"{base_url}/tasks/index-file",
                    payload.model_dump(),
                )
                tasks_enqueued += 1

            total_enqueued += tasks_enqueued

            logger.info(
                "backfill_repo_complete",
                owner=item.owner,
                repo=item.repo,
                files_found=len(files),
                tasks_enqueued=tasks_enqueued,
                files_skipped=files_skipped,
            )

            results.append(
                BackfillRepoResult(
                    owner=item.owner,
                    repo=item.repo,
                    status="accepted",
                    files_found=len(files),
                    tasks_enqueued=tasks_enqueued,
                    files_skipped_denylist=files_skipped,
                )
            )
        except Exception as exc:
            logger.error(
                "backfill_repo_failed",
                owner=item.owner,
                repo=item.repo,
                error=str(exc),
            )
            results.append(
                BackfillRepoResult(
                    owner=item.owner,
                    repo=item.repo,
                    status="error",
                    error=str(exc),
                )
            )

    return BackfillResponse(results=results, total_tasks_enqueued=total_enqueued)


@router.post("/ingest-url")
async def ingest_url(
    request: IngestURLRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> IngestURLResponse:
    """Fetch a web page and ingest its text content into the knowledge base."""
    # Fetch URL content
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(request.url)
        resp.raise_for_status()

    # Extract text from HTML
    text = extract_text_from_html(resp.text)

    # Derive path from URL if not provided
    path = request.path
    if not path:
        parsed = urlparse(request.url)
        path = parsed.path.strip("/") or "index"

    # Synthetic repo_id from owner+name (no GitHub integer ID for private repos)
    synthetic_id = abs(hash(f"{request.repo_owner}/{request.repo_name}")) % (2**31)
    await get_or_create_repo(session, synthetic_id, request.repo_owner, request.repo_name)

    # Content hash for dedup
    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    commit_sha = content_hash[:40]

    # Upsert KBFile
    result = await session.execute(
        select(KBFile).where(KBFile.repo_id == synthetic_id, KBFile.path == path)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        if existing.sha256 == content_hash:
            return IngestURLResponse(status="unchanged", chunks_created=0)
        # Delete old chunks
        await session.execute(delete(KBChunk).where(KBChunk.file_id == existing.id))
        existing.sha256 = content_hash
        existing.commit_sha = commit_sha
        kb_file = existing
    else:
        kb_file = KBFile(
            repo_id=synthetic_id,
            path=path,
            commit_sha=commit_sha,
            sha256=content_hash,
        )
        session.add(kb_file)
        await session.flush()

    # Chunk and create records
    chunks = chunk_file(text, path)
    for start_line, end_line, chunk_content in chunks:
        chunk = KBChunk(
            repo_id=synthetic_id,
            file_id=kb_file.id,
            path=path,
            commit_sha=commit_sha,
            start_line=start_line,
            end_line=end_line,
            content=chunk_content,
        )
        session.add(chunk)

    logger.info(
        "url_ingested",
        url=request.url,
        path=path,
        chunks=len(chunks),
    )

    return IngestURLResponse(status="ingested", chunks_created=len(chunks))
