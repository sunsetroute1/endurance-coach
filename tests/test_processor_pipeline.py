"""Tests for processor pipeline."""

import pytest
from tests.fixtures.garmin_payloads import USER_ID, activity_payload, sleep_payload

from endurance_coach.domain.enums import ResourceType
from endurance_coach.processor.pipeline import DefaultProcessorPipeline


class StubRawRepo:
    def __init__(self, payloads):
        self.payloads = payloads
        self.processed: list = []

    async def list_unprocessed(self, user_id, resource_type, limit=100):
        return [p for p in self.payloads if p.resource_type == resource_type][:limit]

    async def mark_processed(self, payload_id):
        self.processed.append(payload_id)


class StubNormalizedRepo:
    def __init__(self) -> None:
        self.activities = []
        self.sleep = []
        self.dynamics = []

    async def upsert_activity(self, record):
        row = type("ActivityRow", (), {"id": record.source_payload_id})()
        self.activities.append(record)
        return row

    async def upsert_sleep(self, record):
        self.sleep.append(record)
        return record

    async def upsert_hrv(self, record):
        return record

    async def upsert_readiness(self, record):
        return record

    async def upsert_body_battery(self, record):
        return record

    async def upsert_stress(self, record):
        return record

    async def upsert_steps(self, record):
        return record

    async def upsert_running_dynamics(self, record):
        self.dynamics.append(record)
        return record


@pytest.mark.asyncio
async def test_pipeline_processes_activity_and_sleep() -> None:
    activity = activity_payload().model_copy(update={"user_id": USER_ID})
    sleep = sleep_payload().model_copy(update={"user_id": USER_ID})

    raw_repo = StubRawRepo([activity, sleep])
    normalized_repo = StubNormalizedRepo()
    pipeline = DefaultProcessorPipeline(raw_repo, normalized_repo)  # type: ignore[arg-type]

    processed = await pipeline.process_all_pending(USER_ID, limit_per_type=10)

    assert processed[ResourceType.ACTIVITIES] == 1
    assert processed[ResourceType.SLEEP] == 1
    assert len(normalized_repo.activities) == 1
    assert len(normalized_repo.sleep) == 1
    assert len(normalized_repo.dynamics) == 1
    assert len(raw_repo.processed) == 2
