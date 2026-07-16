"""API tests for morning readiness gating."""

from datetime import UTC, date, datetime, time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from endurance_coach.api.deps import get_container, get_request_services
from endurance_coach.api.main import app
from endurance_coach.config import get_settings
from endurance_coach.garmin.daily_readiness import (
    DailyGarminReadinessService,
    ReadinessCompletionStatus,
)


class PartialRepo:
    async def get_hrv_for_date(self, user_id, target_date):
        return None

    async def get_sleep_for_date(self, user_id, sleep_date):
        return None

    async def get_latest_body_battery(self, user_id, as_of):
        return None

    async def get_latest_stress(self, user_id, as_of):
        return None

    async def get_steps_for_date(self, user_id, step_date):
        return None

    async def get_recent_activities(self, user_id, limit: int = 10):
        return []

    async def get_raw_payload(self, payload_id):
        return None


class StubUser:
    id = uuid4()
    email = "athlete@localhost"


class StubUserRepo:
    async def get_or_create_default(self, email):
        return StubUser()


class StubServices:
    def __init__(self) -> None:
        self.user_repo = StubUserRepo()
        self.analytics_repo = PartialRepo()


class StubContainer:
    settings = type(
        "Settings",
        (),
        {"default_user_email": "athlete@localhost", "app_timezone": "America/Denver"},
    )()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("API_SECRET_KEY", "")
    get_settings.cache_clear()
    services = StubServices()
    app.dependency_overrides[get_request_services] = lambda: services
    app.dependency_overrides[get_container] = lambda: StubContainer()
    yield TestClient(app)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_daily_readiness_returns_404_when_partial(client: TestClient) -> None:
    response = client.get("/api/v1/garmin/daily-readiness?date=2026-07-16")
    assert response.status_code == 404
    body = response.json()["detail"]
    assert body["status"] == ReadinessCompletionStatus.PARTIAL.value
    assert body["missing_fields"]


def test_morning_readiness_status_always_returns_shape(client: TestClient) -> None:
    response = client.get("/api/v1/garmin/morning-readiness-status?date=2026-07-16")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == ReadinessCompletionStatus.PARTIAL.value
    assert "missing_fields" in body
