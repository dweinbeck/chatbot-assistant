"""GitHub webhook router with HMAC-SHA256 signature verification."""

import hashlib
import hmac
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.config import settings
from app.dependencies import get_task_queue
from app.schemas.tasks import DeleteFilePayload, IndexFilePayload
from app.schemas.webhooks import PushWebhookPayload
from app.services.task_queue import TaskQueue

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def verify_github_signature(
    request: Request,
    x_hub_signature_256: str = Header(...),
) -> bytes:
    """Verify GitHub webhook HMAC-SHA256 signature.

    Reads the raw request body, computes the expected signature using the
    configured webhook secret, and performs a constant-time comparison.

    Returns the raw body bytes on success so the route handler can parse
    the payload without reading the body stream a second time.

    Raises:
        HTTPException: 401 if signature does not match.
    """
    body = await request.body()
    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )
    return body


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    raw_body: bytes = Depends(verify_github_signature),
    task_queue: Annotated[TaskQueue, Depends(get_task_queue)] = None,  # type: ignore[assignment]
) -> dict:
    """Receive a GitHub push webhook event.

    Parses the payload and enqueues index/delete tasks for each file
    mentioned in the push commits.
    """
    payload = PushWebhookPayload.model_validate_json(raw_body)

    if payload.deleted:
        logger.info("webhook_skipped_deletion", ref=payload.ref)
        return {"status": "accepted", "tasks_enqueued": 0}

    base_url = settings.task_handler_base_url
    repo = payload.repository
    repo_owner = repo.owner.login or repo.owner.name or ""
    repo_name = repo.name
    repo_id = repo.id
    commit_sha = payload.after

    tasks_enqueued = 0

    for commit in payload.commits:
        # Enqueue index tasks for added and modified files
        for path in commit.added + commit.modified:
            index_payload = IndexFilePayload(
                repo_owner=repo_owner,
                repo_name=repo_name,
                repo_id=repo_id,
                path=path,
                commit_sha=commit_sha,
            )
            await task_queue.enqueue(
                f"{base_url}/tasks/index-file",
                index_payload.model_dump(),
            )
            tasks_enqueued += 1

        # Enqueue delete tasks for removed files
        for path in commit.removed:
            delete_payload = DeleteFilePayload(
                repo_owner=repo_owner,
                repo_name=repo_name,
                repo_id=repo_id,
                path=path,
            )
            await task_queue.enqueue(
                f"{base_url}/tasks/delete-file",
                delete_payload.model_dump(),
            )
            tasks_enqueued += 1

    logger.info("webhook_processed", commits=len(payload.commits), tasks_enqueued=tasks_enqueued)
    return {"status": "accepted", "tasks_enqueued": tasks_enqueued}
