"""HTTP middleware for the FastAPI application."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from endurance_coach.config import get_settings
from endurance_coach.security.api_key import verify_bearer_token

PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        if not settings.api_secret_key:
            return await call_next(request)

        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        if not verify_bearer_token(request.headers.get("authorization"), settings.api_secret_key):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        return await call_next(request)
