"""API key middleware for protecting non-public routes."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

# Prefixes that bypass API key validation
_EXEMPT_PREFIXES = ("/health", "/webhooks/")


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Require a valid X-API-Key header on protected routes.

    Behaviour:
    - When ``settings.api_key`` is empty the middleware is a no-op (local dev).
    - ``/health`` and ``/webhooks/*`` are always exempt.
    - All other routes must include a matching ``X-API-Key`` header.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not settings.api_key:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)

        provided = request.headers.get("X-API-Key")
        if not provided or provided != settings.api_key:
            return JSONResponse(
                status_code=401, content={"detail": "Invalid or missing API key"}
            )

        return await call_next(request)
