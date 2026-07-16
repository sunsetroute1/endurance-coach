"""Safely backfill Garmin activity payloads with lap splits."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from endurance_coach.collector.hashing import payload_content_hash
from endurance_coach.collector.providers.garmin.client import GarminClient
from endurance_coach.collector.repositories import SqlAlchemyRawPayloadRepository
from endurance_coach.db.models import ActivityRecord, RawPayloadRecord

logger = logging.getLogger(__name__)

RATE_LIMIT_MARKERS = ("429", "rate limit", "too many requests", "throttl")


@dataclass
class ActivityBackfillResult:
    total_candidates: int
    updated: int
    skipped: int
    failed: int
    errors: tuple[str, ...]


def _payload_has_laps(payload: dict[str, Any]) -> bool:
    detail = payload.get("detail", {})
    if not isinstance(detail, dict):
        return False
    laps = detail.get("lapDTOs")
    return isinstance(laps, list) and len(laps) > 0


def _is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in RATE_LIMIT_MARKERS)


class GarminActivityBackfillService:
    """Fetch missing lap splits and merge them into stored activity payloads."""

    def __init__(
        self,
        session: AsyncSession,
        client: GarminClient,
        *,
        delay_seconds: float = 1.5,
        batch_size: int = 10,
        max_retries: int = 4,
    ) -> None:
        self._session = session
        self._client = client
        self._raw_repo = SqlAlchemyRawPayloadRepository(session)
        self._delay_seconds = delay_seconds
        self._batch_size = batch_size
        self._max_retries = max_retries

    async def list_candidates(self, user_id: UUID, *, limit: int | None = None) -> list[ActivityRecord]:
        result = await self._session.execute(
            select(ActivityRecord)
            .where(ActivityRecord.user_id == user_id)
            .order_by(ActivityRecord.started_at.desc())
        )
        activities = list(result.scalars().all())
        if limit is not None:
            activities = activities[:limit]
        return activities

    async def backfill(
        self,
        user_id: UUID,
        *,
        limit: int | None = None,
        full_refresh: bool = False,
        dry_run: bool = False,
    ) -> ActivityBackfillResult:
        activities = await self.list_candidates(user_id, limit=limit)
        updated = 0
        skipped = 0
        failed = 0
        errors: list[str] = []

        since_last_commit = 0
        for index, activity in enumerate(activities, start=1):
            try:
                outcome = await self._backfill_activity(
                    activity,
                    full_refresh=full_refresh,
                    dry_run=dry_run,
                )
            except Exception as exc:
                failed += 1
                message = f"{activity.provider_record_id}: {exc}"
                errors.append(message)
                logger.exception("Backfill failed for activity %s", activity.provider_record_id)
                if _is_rate_limit_error(exc):
                    backoff = min(self._delay_seconds * 8, 60.0)
                    logger.warning("Rate limit detected, sleeping %.1fs", backoff)
                    await asyncio.sleep(backoff)
                continue

            if outcome == "updated":
                updated += 1
                since_last_commit += 1
            else:
                skipped += 1

            if not dry_run and since_last_commit >= self._batch_size:
                await self._session.commit()
                since_last_commit = 0
                logger.info("Committed batch at activity %s/%s", index, len(activities))

            if index < len(activities):
                await asyncio.sleep(self._delay_seconds)

        if not dry_run:
            await self._session.commit()

        return ActivityBackfillResult(
            total_candidates=len(activities),
            updated=updated,
            skipped=skipped,
            failed=failed,
            errors=tuple(errors),
        )

    async def _backfill_activity(
        self,
        activity: ActivityRecord,
        *,
        full_refresh: bool,
        dry_run: bool,
    ) -> str:
        record = await self._raw_repo.get_record_by_id(activity.source_payload_id)
        if record is None:
            raise ValueError(f"Missing raw payload for activity {activity.provider_record_id}")

        payload = dict(record.payload)
        if not full_refresh and _payload_has_laps(payload):
            logger.debug("Skipping %s — lapDTOs already present", activity.provider_record_id)
            return "skipped"

        detail = payload.get("detail", {})
        if not isinstance(detail, dict):
            detail = {}

        if full_refresh:
            detail = await self._call_with_retry(self._client.get_activity, activity.provider_record_id)
            await asyncio.sleep(self._delay_seconds / 2)

        laps = await self._call_with_retry(self._client.get_activity_laps, activity.provider_record_id)
        if laps:
            detail = {**detail, "lapDTOs": laps}

        payload["detail"] = detail
        if dry_run:
            logger.info(
                "Dry run: would update %s with %s laps",
                activity.provider_record_id,
                len(laps),
            )
            return "updated" if laps else "skipped"

        await self._raw_repo.update_payload(
            record.id,
            payload=payload,
            content_hash=payload_content_hash(payload),
        )
        logger.info(
            "Updated %s (%s) with %s laps",
            activity.provider_record_id,
            activity.name,
            len(laps),
        )
        return "updated" if laps else "skipped"

    async def _call_with_retry(self, method: Any, activity_id: str) -> Any:
        delay = self._delay_seconds
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                return await method(activity_id)
            except Exception as exc:
                last_error = exc
                if not _is_rate_limit_error(exc) or attempt == self._max_retries:
                    raise
                logger.warning(
                    "Rate limited on %s (attempt %s/%s), backing off %.1fs",
                    activity_id,
                    attempt,
                    self._max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"Failed to call Garmin for activity {activity_id}")
