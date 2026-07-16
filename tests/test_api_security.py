"""Tests for API key middleware."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from endurance_coach.api.middleware import ApiKeyMiddleware
from endurance_coach.config import get_settings


def test_api_key_middleware_blocks_protected_route(monkeypatch) -> None:
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    get_settings.cache_clear()

    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.get("/api/v1/example")
    async def example() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.get("/health")
    async def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    with TestClient(app) as client:
        denied = client.get("/api/v1/example")
        assert denied.status_code == 401

        allowed = client.get(
            "/api/v1/example",
            headers={"Authorization": "Bearer test-secret"},
        )
        assert allowed.status_code == 200

        health = client.get("/health")
        assert health.status_code == 200

    get_settings.cache_clear()


def test_api_key_middleware_allows_all_when_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("API_SECRET_KEY", raising=False)
    get_settings.cache_clear()

    app = FastAPI()
    app.add_middleware(ApiKeyMiddleware)

    @app.get("/api/v1/example")
    async def example() -> PlainTextResponse:
        return PlainTextResponse("ok")

    with TestClient(app) as client:
        response = client.get("/api/v1/example")
        assert response.status_code == 200

    get_settings.cache_clear()
