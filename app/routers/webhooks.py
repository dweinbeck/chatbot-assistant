"""GitHub webhook router with HMAC-SHA256 signature verification."""

import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.config import settings
from app.schemas.webhooks import PushWebhookPayload

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
) -> dict:
    """Receive a GitHub push webhook event.

    The signature dependency has already verified authenticity and provided
    the raw body bytes. This endpoint parses the payload and acknowledges
    receipt. Task enqueuing will be wired in plan 02-04.
    """
    payload = PushWebhookPayload.model_validate_json(raw_body)
    return {"status": "accepted", "commits": len(payload.commits)}
