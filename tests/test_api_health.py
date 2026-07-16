"""Tests for API endpoints."""

from fastapi.testclient import TestClient

from endurance_coach.api.main import app


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "meta" in data
        assert data["meta"]["timezone"] == "America/Denver"
        assert "response_generated_at" in data["meta"]


def test_server_info_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/server")
        assert response.status_code == 200
        data = response.json()
        assert data["public_base_url"] == "http://127.0.0.1:8000"
        assert "version" in data
        assert "meta" in data
        assert "response_generated_at" in data["meta"]
