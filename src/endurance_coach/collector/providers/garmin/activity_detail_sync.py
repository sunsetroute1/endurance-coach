"""Incremental Garmin activity-chart collection.

This path is separate from activity sync and from lap backfill. It stores the
chart response as its own raw payload and skips activities already collected.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from endurance_coach.collector.hashing import payload_content_hash
from endurance_coach.collector.providers.garmin.token_store import garmin_auth_pause_reason
from endurance_coach.collector.repositories import SqlAlchemyRawPayloadRepository
from endurance_coach.db.models import (
    ActivityDetailCollectionRecord,
    ActivityDetailSampleRecord,
    ActivityRecord,
    RawPayloadRecord,
)
from endurance_coach.domain.enums import DataProviderType, ResourceType
from endurance_coach.domain.models import RawPayload
from endurance_coach.garmin.activity_series import parse_activity_detail_chart

logger = logging.getLogger(__name__)

OUTDOOR_TYPES = ("running", "trail_running")
MIN_OUTDOOR_SECONDS = 1200
_SAMPLE_COLUMNS = (
    "elapsed_seconds",
    "heart_rate_bpm",
    "power_watts",
    "run_cadence_spm",
    "step_cadence_spm",
    "potential_stamina",
    "available_stamina",
    "elevation_meters",
    "speed_mps",
    "grade_adjusted_speed_mps",
)


@dataclass(frozen=True)
class DetailJob:
    user_id: UUID
    activity_id: UUID
    provider_activity_id: str


@dataclass(frozen=True)
class DetailCollectResult:
    requested: int
    collected: int
    skipped: int
    unsupported: int
    failed: int
    downloaded: int
    stopped_reason: str | None
    errors: tuple[str, ...]


class ActivityDetailClient(Protocol):
    async def get_activity_details(
        self,
        activity_id: str,
        *,
        maxchart: int = 20000,
    ) -> dict[str, Any]: ...


class ActivityDetailStore(Protocol):
    async def get_status(self, user_id: UUID, provider_activity_id: str) -> str | None: ...

    async def get_raw(
        self,
        user_id: UUID,
        provider_activity_id: str,
    ) -> tuple[UUID, dict[str, Any]] | None: ...

    async def save_raw(self, job: DetailJob, payload: dict[str, Any]) -> UUID: ...

    async def replace_samples(
        self,
        job: DetailJob,
        source_payload_id: UUID,
        samples: list[dict[str, Any]],
    ) -> None: ...

    async def save_status(
        self,
        job: DetailJob,
        *,
        status: str,
        sample_count: int,
        metric_keys: dict[str, Any],
        median_interval_seconds: float | None,
        source_payload_id: UUID | None,
        error_message: str | None,
    ) -> None: ...


class SqlActivityDetailStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._raw = SqlAlchemyRawPayloadRepository(session)

    async def get_status(self, user_id: UUID, provider_activity_id: str) -> str | None:
        result = await self._session.execute(
            select(ActivityDetailCollectionRecord.status).where(
                ActivityDetailCollectionRecord.user_id == user_id,
                ActivityDetailCollectionRecord.provider == DataProviderType.GARMIN.value,
                ActivityDetailCollectionRecord.provider_activity_id == provider_activity_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_raw(
        self,
        user_id: UUID,
        provider_activity_id: str,
    ) -> tuple[UUID, dict[str, Any]] | None:
        result = await self._session.execute(
            select(RawPayloadRecord)
            .where(
                RawPayloadRecord.user_id == user_id,
                RawPayloadRecord.provider == DataProviderType.GARMIN.value,
                RawPayloadRecord.resource_type == ResourceType.ACTIVITY_DETAILS.value,
                RawPayloadRecord.provider_record_id == provider_activity_id,
            )
            .order_by(RawPayloadRecord.fetched_at.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return record.id, record.payload

    async def save_raw(self, job: DetailJob, payload: dict[str, Any]) -> UUID:
        saved = await self._raw.save(
            RawPayload(
                user_id=job.user_id,
                provider=DataProviderType.GARMIN,
                resource_type=ResourceType.ACTIVITY_DETAILS,
                provider_record_id=job.provider_activity_id,
                payload=payload,
                content_hash=payload_content_hash(payload),
                fetched_at=datetime.now(UTC),
            )
        )
        if saved.id is None:
            raise RuntimeError("Raw activity detail was not stored")
        return saved.id

    async def replace_samples(
        self,
        job: DetailJob,
        source_payload_id: UUID,
        samples: list[dict[str, Any]],
    ) -> None:
        await self._session.execute(
            delete(ActivityDetailSampleRecord).where(
                ActivityDetailSampleRecord.activity_id == job.activity_id
            )
        )
        rows = [_sample_row(job, source_payload_id, sample) for sample in samples]
        for start in range(0, len(rows), 2000):
            chunk = rows[start : start + 2000]
            await self._session.execute(insert(ActivityDetailSampleRecord), chunk)

    async def save_status(
        self,
        job: DetailJob,
        *,
        status: str,
        sample_count: int,
        metric_keys: dict[str, Any],
        median_interval_seconds: float | None,
        source_payload_id: UUID | None,
        error_message: str | None,
    ) -> None:
        now = datetime.now(UTC)
        statement = pg_insert(ActivityDetailCollectionRecord).values(
            id=uuid4(),
            user_id=job.user_id,
            provider=DataProviderType.GARMIN.value,
            provider_activity_id=job.provider_activity_id,
            activity_id=job.activity_id,
            status=status,
            sample_count=sample_count,
            metric_keys=metric_keys,
            median_interval_seconds=median_interval_seconds,
            error_message=error_message,
            source_payload_id=source_payload_id,
            attempted_at=now,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_activity_detail_collection",
            set_={
                "status": status,
                "sample_count": sample_count,
                "metric_keys": metric_keys,
                "median_interval_seconds": median_interval_seconds,
                "error_message": error_message,
                "source_payload_id": source_payload_id,
                "attempted_at": now,
                "activity_id": job.activity_id,
            },
        )
        await self._session.execute(statement)
        await self._session.commit()

    async def outdoor_jobs(
        self,
        user_id: UUID,
        *,
        limit: int,
        provider_activity_ids: list[str] | None = None,
    ) -> list[DetailJob]:
        statement = select(ActivityRecord).where(
            ActivityRecord.user_id == user_id,
            ActivityRecord.provider == DataProviderType.GARMIN.value,
            ActivityRecord.activity_type.in_(OUTDOOR_TYPES),
        )
        if provider_activity_ids:
            statement = statement.where(
                ActivityRecord.provider_record_id.in_(provider_activity_ids)
            )
        else:
            statement = statement.where(ActivityRecord.duration_seconds >= MIN_OUTDOOR_SECONDS)
        statement = statement.order_by(ActivityRecord.started_at.desc()).limit(limit)
        result = await self._session.execute(statement)
        return [
            DetailJob(
                user_id=user_id,
                activity_id=row.id,
                provider_activity_id=row.provider_record_id,
            )
            for row in result.scalars().all()
        ]

    async def collection_row(
        self,
        user_id: UUID,
        provider_activity_id: str,
    ) -> tuple[ActivityDetailCollectionRecord, ActivityRecord] | None:
        result = await self._session.execute(
            select(ActivityDetailCollectionRecord, ActivityRecord)
            .join(ActivityRecord, ActivityRecord.id == ActivityDetailCollectionRecord.activity_id)
            .where(
                ActivityDetailCollectionRecord.user_id == user_id,
                ActivityDetailCollectionRecord.provider_activity_id == provider_activity_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        return row[0], row[1]

    async def samples(self, activity_id: UUID) -> list[ActivityDetailSampleRecord]:
        result = await self._session.execute(
            select(ActivityDetailSampleRecord)
            .where(ActivityDetailSampleRecord.activity_id == activity_id)
            .order_by(ActivityDetailSampleRecord.sample_index)
        )
        return list(result.scalars().all())

    async def list_collections(
        self,
        user_id: UUID,
        *,
        limit: int = 200,
    ) -> list[tuple[ActivityDetailCollectionRecord, ActivityRecord]]:
        result = await self._session.execute(
            select(ActivityDetailCollectionRecord, ActivityRecord)
            .join(
                ActivityRecord,
                ActivityRecord.id == ActivityDetailCollectionRecord.activity_id,
            )
            .where(ActivityDetailCollectionRecord.user_id == user_id)
            .order_by(ActivityRecord.started_at)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def collected_activities(self, user_id: UUID, *, limit: int = 80) -> list[ActivityRecord]:
        result = await self._session.execute(
            select(ActivityRecord)
            .join(
                ActivityDetailCollectionRecord,
                ActivityDetailCollectionRecord.activity_id == ActivityRecord.id,
            )
            .where(
                ActivityDetailCollectionRecord.user_id == user_id,
                ActivityDetailCollectionRecord.status == "collected",
            )
            .order_by(ActivityRecord.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def backfill_status(self, user_id: UUID) -> dict[str, Any]:
        eligible = await self._count(
            select(func.count())
            .select_from(ActivityRecord)
            .where(
                ActivityRecord.user_id == user_id,
                ActivityRecord.provider == DataProviderType.GARMIN.value,
                ActivityRecord.activity_type.in_(OUTDOOR_TYPES),
                ActivityRecord.duration_seconds >= MIN_OUTDOOR_SECONDS,
            )
        )
        status_counts = await self._session.execute(
            select(ActivityDetailCollectionRecord.status, func.count())
            .where(ActivityDetailCollectionRecord.user_id == user_id)
            .group_by(ActivityDetailCollectionRecord.status)
        )
        counts = {status: count for status, count in status_counts.all()}
        touched = sum(counts.values())
        field_counts = {}
        for column in (
            "heart_rate_bpm",
            "power_watts",
            "run_cadence_spm",
            "potential_stamina",
            "available_stamina",
            "grade_adjusted_speed_mps",
            "elevation_meters",
        ):
            field_counts[column] = await self._count(
                select(func.count(func.distinct(ActivityDetailSampleRecord.activity_id))).where(
                    ActivityDetailSampleRecord.user_id == user_id,
                    getattr(ActivityDetailSampleRecord, column).is_not(None),
                )
            )
        last = await self._session.execute(
            select(func.max(ActivityDetailCollectionRecord.attempted_at)).where(
                ActivityDetailCollectionRecord.user_id == user_id
            )
        )
        attempted = last.scalar_one()
        return {
            "eligible_outdoor_runs": eligible,
            "collected": counts.get("collected", 0),
            "unsupported": counts.get("unsupported", 0),
            "failed": counts.get("failed", 0),
            "remaining_eligible": max(eligible - touched, 0),
            "activities_with_field": field_counts,
            "last_attempt": attempted.isoformat() if attempted is not None else None,
            "note": (
                "Eligible means a Garmin run or trail run of at least 20 minutes. "
                "Collected activities are skipped. Failed activities can be retried. "
                "Unsupported charts are not requested again."
            ),
        }

    async def _count(self, statement: Any) -> int:
        result = await self._session.execute(statement)
        return int(result.scalar_one())


class GarminActivityDetailCollector:
    def __init__(
        self,
        client: ActivityDetailClient,
        store: ActivityDetailStore,
        *,
        maxchart: int = 20000,
        pause_seconds: float = 1.0,
        sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._maxchart = maxchart
        self._pause_seconds = pause_seconds
        self._sleeper = sleeper or asyncio.sleep

    async def collect(self, jobs: list[DetailJob]) -> DetailCollectResult:
        collected = skipped = unsupported = failed = downloaded = 0
        errors: list[str] = []
        stopped: str | None = None
        for index, job in enumerate(jobs):
            outcome, did_download, fatal = await self._one(job)
            downloaded += int(did_download)
            if outcome == "collected":
                collected += 1
            elif outcome == "skipped":
                skipped += 1
            elif outcome == "unsupported":
                unsupported += 1
            else:
                failed += 1
                if fatal:
                    errors.append(fatal)
            if fatal and garmin_auth_pause_reason(RuntimeError(fatal)):
                stopped = garmin_auth_pause_reason(RuntimeError(fatal))
                break
            if did_download and index < len(jobs) - 1 and self._pause_seconds > 0:
                await self._sleeper(self._pause_seconds)
        return DetailCollectResult(
            requested=len(jobs),
            collected=collected,
            skipped=skipped,
            unsupported=unsupported,
            failed=failed,
            downloaded=downloaded,
            stopped_reason=stopped,
            errors=tuple(errors),
        )

    async def _one(self, job: DetailJob) -> tuple[str, bool, str | None]:
        status = await self._store.get_status(job.user_id, job.provider_activity_id)
        if status in {"collected", "unsupported"}:
            return "skipped", False, None
        downloaded = False
        try:
            existing = await self._store.get_raw(job.user_id, job.provider_activity_id)
            if existing is None:
                payload = await self._client.get_activity_details(
                    job.provider_activity_id,
                    maxchart=self._maxchart,
                )
                downloaded = True
                source_id = await self._store.save_raw(job, payload)
            else:
                source_id, payload = existing
            parsed = parse_activity_detail_chart(payload)
        except Exception as exc:
            message = _safe_error(exc)
            await self._store.save_status(
                job,
                status="failed",
                sample_count=0,
                metric_keys={},
                median_interval_seconds=None,
                source_payload_id=None,
                error_message=message,
            )
            logger.warning("Activity detail failed for %s", job.provider_activity_id)
            return "failed", downloaded, message
        if not parsed["priority_fields_present"]:
            await self._store.save_status(
                job,
                status="unsupported",
                sample_count=0,
                metric_keys={
                    "fields_present": parsed["fields_present"],
                    "units": parsed["units"],
                    "factors_applied": False,
                },
                median_interval_seconds=parsed["sampling"]["median_interval_seconds"],
                source_payload_id=source_id,
                error_message=None,
            )
            return "unsupported", downloaded, None
        await self._store.replace_samples(job, source_id, parsed["samples"])
        await self._store.save_status(
            job,
            status="collected",
            sample_count=len(parsed["samples"]),
            metric_keys={
                "fields_present": parsed["fields_present"],
                "units": parsed["units"],
                "factors_applied": False,
                "max_interval_seconds": parsed["sampling"]["max_interval_seconds"],
            },
            median_interval_seconds=parsed["sampling"]["median_interval_seconds"],
            source_payload_id=source_id,
            error_message=None,
        )
        return "collected", downloaded, None


def sample_to_dict(row: ActivityDetailSampleRecord) -> dict[str, Any]:
    return {
        "sample_index": row.sample_index,
        "recorded_at": row.recorded_at,
        "elapsed_seconds": row.elapsed_seconds,
        "heart_rate_bpm": row.heart_rate_bpm,
        "power_watts": row.power_watts,
        "run_cadence_spm": row.run_cadence_spm,
        "step_cadence_spm": row.step_cadence_spm,
        "potential_stamina": row.potential_stamina,
        "available_stamina": row.available_stamina,
        "elevation_meters": row.elevation_meters,
        "speed_mps": row.speed_mps,
        "grade_adjusted_speed_mps": row.grade_adjusted_speed_mps,
    }


def _sample_row(job: DetailJob, source_payload_id: UUID, sample: dict[str, Any]) -> dict[str, Any]:
    row = {
        "id": uuid4(),
        "user_id": job.user_id,
        "activity_id": job.activity_id,
        "source_payload_id": source_payload_id,
        "sample_index": sample["sample_index"],
        "recorded_at": sample.get("recorded_at"),
    }
    for column in _SAMPLE_COLUMNS:
        row[column] = sample.get(column)
    return row


def _safe_error(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:500]
