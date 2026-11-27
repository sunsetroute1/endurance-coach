"""HTTP middleware for the FastAPI application."""

from __future__ import annotations

import re

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from endurance_coach.config import get_settings
from endurance_coach.garmin.phone_login import GRANT_HEADER, grant_is_valid
from endurance_coach.security.api_key import verify_bearer_token

PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})
GARMIN_LOGIN_PAGE = "/api/v1/garmin/login"
_GARMIN_LOGIN_POST = re.compile(r"^/api/v1/garmin/login(?:/[A-Za-z0-9_-]+/code)?$")


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        if not settings.api_secret_key:
            return await call_next(request)

        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        if request.method == "GET" and request.url.path == GARMIN_LOGIN_PAGE:
            return await call_next(request)

        if request.method == "POST" and _GARMIN_LOGIN_POST.match(request.url.path):
            bearer_ok = verify_bearer_token(
                request.headers.get("authorization"),
                settings.api_secret_key,
            )
            if bearer_ok or grant_is_valid(request.headers.get(GRANT_HEADER)):
                return await call_next(request)
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        if not verify_bearer_token(request.headers.get("authorization"), settings.api_secret_key):
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        return await call_next(request)
