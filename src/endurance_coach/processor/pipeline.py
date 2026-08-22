"""Default processor pipeline implementation."""

from __future__ import annotations

import logging
from uuid import UUID

from endurance_coach.collector.repositories import SqlAlchemyRawPayloadRepository
from endurance_coach.domain.enums import DataProviderType, ResourceType
from endurance_coach.domain.models import RawPayload
from endurance_coach.processor.providers.garmin.normalizers import (
    GarminActivityNormalizer,
    GarminBodyBatteryNormalizer,
    GarminHRVNormalizer,
    GarminReadinessNormalizer,
    GarminSleepNormalizer,
    GarminStepsNormalizer,
    GarminStressNormalizer,
)
from endurance_coach.processor.providers.strava.normalizers import StravaActivityNormalizer
from endurance_coach.processor.providers.samsung.normalizers import (
    SamsungActivityNormalizer,
    SamsungHRVNormalizer,
    SamsungSleepNormalizer,
    SamsungStepsNormalizer,
    SamsungStressNormalizer,
)
from endurance_coach.processor.repositories import SqlAlchemyNormalizedRecordRepository

logger = logging.getLogger(__name__)

PROCESSABLE_RESOURCES = (
    ResourceType.ACTIVITIES,
    ResourceType.SLEEP,
    ResourceType.HRV,
    ResourceType.BODY_BATTERY,
    ResourceType.TRAINING_READINESS,
    ResourceType.STRESS,
    ResourceType.STEPS,
)


class DefaultProcessorPipeline:
    def __init__(
        self,
        raw_payload_repo: SqlAlchemyRawPayloadRepository,
        normalized_repo: SqlAlchemyNormalizedRecordRepository,
    ) -> None:
        self._raw_payload_repo = raw_payload_repo
        self._normalized_repo = normalized_repo
        self._activity_normalizer = GarminActivityNormalizer()
        self._strava_activity_normalizer = StravaActivityNormalizer()
        self._sleep_normalizer = GarminSleepNormalizer()
        self._hrv_normalizer = GarminHRVNormalizer()
        self._readiness_normalizer = GarminReadinessNormalizer()
        self._body_battery_normalizer = GarminBodyBatteryNormalizer()
        self._stress_normalizer = GarminStressNormalizer()
        self._steps_normalizer = GarminStepsNormalizer()
        self._samsung_activity_normalizer = SamsungActivityNormalizer()
        self._samsung_sleep_normalizer = SamsungSleepNormalizer()
        self._samsung_steps_normalizer = SamsungStepsNormalizer()
        self._samsung_hrv_normalizer = SamsungHRVNormalizer()
        self._samsung_stress_normalizer = SamsungStressNormalizer()

    async def process_pending(
        self,
        user_id: UUID,
        resource_type: ResourceType,
        limit: int = 100,
    ) -> int:
        payloads = await self._raw_payload_repo.list_unprocessed(user_id, resource_type, limit)
        processed = 0
        for payload in payloads:
            try:
                await self._process_payload(payload)
                if payload.id is not None:
                    await self._raw_payload_repo.mark_processed(payload.id)
                processed += 1
            except Exception:
                logger.exception(
                    "Failed to normalize payload %s (%s)",
                    payload.id,
                    resource_type,
                )
        return processed

    async def process_all_pending(
        self,
        user_id: UUID,
        limit_per_type: int = 100,
    ) -> dict[ResourceType, int]:
        results: dict[ResourceType, int] = {}
        for resource_type in PROCESSABLE_RESOURCES:
            count = await self.process_pending(user_id, resource_type, limit_per_type)
            if count:
                results[resource_type] = count
        return results

    async def _process_payload(self, payload: RawPayload) -> None:
        if payload.provider == DataProviderType.GARMIN:
            await self._process_garmin_payload(payload)
            return
        if payload.provider == DataProviderType.STRAVA:
            await self._process_strava_payload(payload)
            return
        if payload.provider == DataProviderType.SAMSUNG_HEALTH:
            await self._process_samsung_payload(payload)
            return
        raise ValueError(f"Unsupported provider: {payload.provider}")

    async def _process_garmin_payload(self, payload: RawPayload) -> None:
        if payload.resource_type == ResourceType.ACTIVITIES:
            activity = await self._activity_normalizer.normalize(payload)
            row = await self._normalized_repo.upsert_activity(activity)
            dynamics = self._activity_normalizer.extract_running_dynamics(payload, row.id)
            if dynamics is not None:
                await self._normalized_repo.upsert_running_dynamics(dynamics)
            return

        if payload.resource_type == ResourceType.SLEEP:
            sleep = await self._sleep_normalizer.normalize(payload)
            await self._normalized_repo.upsert_sleep(sleep)
            return

        if payload.resource_type == ResourceType.HRV:
            hrv = await self._hrv_normalizer.normalize(payload)
            await self._normalized_repo.upsert_hrv(hrv)
            return

        if payload.resource_type == ResourceType.TRAINING_READINESS:
            readiness = await self._readiness_normalizer.normalize(payload)
            await self._normalized_repo.upsert_readiness(readiness)
            return

        if payload.resource_type == ResourceType.BODY_BATTERY:
            body_battery = await self._body_battery_normalizer.normalize(payload)
            await self._normalized_repo.upsert_body_battery(body_battery)
            return

        if payload.resource_type == ResourceType.STRESS:
            stress = await self._stress_normalizer.normalize(payload)
            await self._normalized_repo.upsert_stress(stress)
            return

        if payload.resource_type == ResourceType.STEPS:
            steps = await self._steps_normalizer.normalize(payload)
            await self._normalized_repo.upsert_steps(steps)
            return

        raise ValueError(f"Unsupported resource type: {payload.resource_type}")

    async def _process_strava_payload(self, payload: RawPayload) -> None:
        if payload.resource_type != ResourceType.ACTIVITIES:
            raise ValueError(f"Unsupported Strava resource type: {payload.resource_type}")
        activity = await self._strava_activity_normalizer.normalize(payload)
        await self._normalized_repo.upsert_activity(activity)

    async def _process_samsung_payload(self, payload: RawPayload) -> None:
        if payload.resource_type == ResourceType.ACTIVITIES:
            activity = await self._samsung_activity_normalizer.normalize(payload)
            await self._normalized_repo.upsert_activity(activity)
            return

        if payload.resource_type == ResourceType.SLEEP:
            sleep = await self._samsung_sleep_normalizer.normalize(payload)
            await self._normalized_repo.upsert_sleep(sleep)
            return

        if payload.resource_type == ResourceType.STEPS:
            steps = await self._samsung_steps_normalizer.normalize(payload)
            await self._normalized_repo.upsert_steps(steps)
            return

        if payload.resource_type == ResourceType.HRV:
            hrv = await self._samsung_hrv_normalizer.normalize(payload)
            await self._normalized_repo.upsert_hrv(hrv)
            return

        if payload.resource_type == ResourceType.STRESS:
            stress = await self._samsung_stress_normalizer.normalize(payload)
            await self._normalized_repo.upsert_stress(stress)
            return

        raise ValueError(f"Unsupported Samsung resource type: {payload.resource_type}")
