"""Garmin Connect data provider — syncs raw payloads via garmin_mcp tokens."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from endurance_coach.collector.hashing import payload_content_hash
from endurance_coach.collector.providers.garmin.client import GarminClient
from endurance_coach.collector.providers.garmin.metrics import (
    HEART_RATE_SPAN_DAYS,
    POWER_CURVE_SPORTS,
    VERIFIED_RANGE_SPAN_DAYS,
    chunk_dates,
    device_ids,
    device_inventory_record,
    economy_records,
    endurance_records,
    garmin_http_status,
    heart_rate_records,
    heat_records,
    hill_records,
    hrv_range_records,
    is_missing_garmin_feature,
    is_unsupported_power_sport,
    lactate_records,
    power_curve_record,
    race_prediction_records,
    respiration_records,
    solar_records,
    spo2_record,
    stamina_record,
    tolerance_records,
    training_status_records,
    vo2_records,
    weight_records,
)
from endurance_coach.collector.providers.garmin.token_store import (
    GarminTokenStore,
    garmin_auth_pause_reason,
    write_garmin_auth_pause,
)
from endurance_coach.collector.repositories import (
    SqlAlchemyProviderConnectionRepository,
    SqlAlchemyRawPayloadRepository,
    SqlAlchemySyncJobRepository,
)
from endurance_coach.domain.enums import DataProviderType, ResourceType, SyncStatus
from endurance_coach.domain.models import RawPayload, SyncRequest, SyncResult
from endurance_coach.garmin.activity_time import garmin_activity_local_date
from endurance_coach.timezone_util import server_timezone_name, today_local, usable_timezone

logger = logging.getLogger(__name__)

SUPPORTED_RESOURCES = (
    ResourceType.ACTIVITIES,
    ResourceType.SLEEP,
    ResourceType.HRV,
    ResourceType.BODY_BATTERY,
    ResourceType.TRAINING_READINESS,
    ResourceType.STRESS,
    ResourceType.STEPS,
    ResourceType.ENDURANCE_SCORE,
    ResourceType.HILL_SCORE,
    ResourceType.RUNNING_TOLERANCE,
    ResourceType.TRAINING_STATUS,
    ResourceType.RACE_PREDICTIONS,
    ResourceType.VO2_MAX,
    ResourceType.HEAT_ACCLIMATION,
    ResourceType.RUNNING_ECONOMY,
    ResourceType.STAMINA_CURVE,
    ResourceType.POWER_CURVE,
    ResourceType.LACTATE_THRESHOLD,
    ResourceType.RESPIRATION,
    ResourceType.SPO2_ACCLIMATION,
    ResourceType.HEART_RATE,
    ResourceType.WEIGHT,
    ResourceType.DEVICES,
    ResourceType.SOLAR_GAIN,
    ResourceType.TRAINING_PLAN,
)

_METRIC_RESOURCES = frozenset(
    {
        ResourceType.ENDURANCE_SCORE,
        ResourceType.HILL_SCORE,
        ResourceType.RUNNING_TOLERANCE,
        ResourceType.TRAINING_STATUS,
        ResourceType.RACE_PREDICTIONS,
        ResourceType.VO2_MAX,
        ResourceType.HEAT_ACCLIMATION,
        ResourceType.RUNNING_ECONOMY,
        ResourceType.STAMINA_CURVE,
        ResourceType.POWER_CURVE,
        ResourceType.LACTATE_THRESHOLD,
        ResourceType.RESPIRATION,
        ResourceType.SPO2_ACCLIMATION,
        ResourceType.HEART_RATE,
        ResourceType.WEIGHT,
        ResourceType.DEVICES,
        ResourceType.SOLAR_GAIN,
        ResourceType.TRAINING_PLAN,
    }
)


def _plan_still_relevant(plan: Any, today: date) -> bool:
    if not isinstance(plan, dict):
        return False
    status = plan.get("trainingStatus")
    status_key = status.get("statusKey") if isinstance(status, dict) else status
    if isinstance(status_key, str) and status_key.lower() in {
        "completed",
        "cancelled",
        "canceled",
        "deleted",
    }:
        return False
    end = plan.get("endDate")
    return not (isinstance(end, str) and len(end) >= 10 and end[:10] < today.isoformat())


class GarminDataProvider:
    def __init__(
        self,
        token_store: GarminTokenStore,
        raw_payload_repo: SqlAlchemyRawPayloadRepository,
        sync_job_repo: SqlAlchemySyncJobRepository,
        connection_repo: SqlAlchemyProviderConnectionRepository,
        sync_days: int = 30,
        timezone: str | None = None,
    ) -> None:
        self._token_store = token_store
        self._raw_payload_repo = raw_payload_repo
        self._sync_job_repo = sync_job_repo
        self._connection_repo = connection_repo
        self._sync_days = sync_days
        self._timezone = usable_timezone(timezone) or server_timezone_name()

    @property
    def provider_type(self) -> DataProviderType:
        return DataProviderType.GARMIN

    def supported_resource_types(self) -> tuple[ResourceType, ...]:
        return SUPPORTED_RESOURCES

    async def is_available(self, user_id: UUID) -> bool:
        return await self._token_store.is_authenticated(user_id, DataProviderType.GARMIN)

    async def sync(self, request: SyncRequest) -> SyncResult:
        errors: list[str] = []
        resources_synced: dict[ResourceType, int] = {}

        valid, auth_error = await self._token_store.validate_tokens()
        if not valid:
            instructions = self._token_store.get_setup_instructions(DataProviderType.GARMIN)
            job = await self._sync_job_repo.create(request)
            error_text = auth_error or "; ".join((instructions.summary, *instructions.steps))
            await self._sync_job_repo.complete(
                job.id,
                status=SyncStatus.FAILED,
                resources_synced={},
                error_message=error_text,
            )
            return SyncResult(
                job_id=job.id,
                provider=self.provider_type,
                status=SyncStatus.FAILED,
                errors=(error_text,),
                completed_at=datetime.now(UTC),
            )

        job = await self._sync_job_repo.create(request)
        await self._connection_repo.upsert_garmin_reference(
            request.user_id,
            str(self._token_store.token_path),
        )

        try:
            client = await GarminClient.from_token_path(self._token_store.token_path)
            await self._remember_profile_timezone(client, request.user_id)
            start_date, end_date = self._resolve_date_window(request)

            for resource_type in request.resource_types:
                if resource_type not in SUPPORTED_RESOURCES:
                    errors.append(f"Unsupported resource type: {resource_type}")
                    continue

                try:
                    count = await self._sync_resource(
                        client=client,
                        request=request,
                        job_id=job.id,
                        resource_type=resource_type,
                        start_date=start_date,
                        end_date=end_date,
                    )
                    resources_synced[resource_type] = count
                except Exception as exc:
                    pause_reason = garmin_auth_pause_reason(exc)
                    if pause_reason:
                        write_garmin_auth_pause(pause_reason)
                        errors.append(pause_reason)
                        break
                    message = f"{resource_type}: {exc}"
                    logger.exception("Garmin sync failed for %s", resource_type)
                    errors.append(message)

            status = SyncStatus.COMPLETED if not errors else SyncStatus.FAILED
            await self._sync_job_repo.complete(
                job.id,
                status=status,
                resources_synced=resources_synced,
                error_message="; ".join(errors) if errors else None,
            )

            return SyncResult(
                job_id=job.id,
                provider=self.provider_type,
                status=status,
                resources_synced=resources_synced,
                errors=tuple(errors),
                completed_at=datetime.now(UTC),
            )
        except Exception as exc:
            logger.exception("Garmin sync failed")
            pause_reason = garmin_auth_pause_reason(exc)
            if pause_reason:
                write_garmin_auth_pause(pause_reason)
                exc = RuntimeError(pause_reason)
            await self._sync_job_repo.complete(
                job.id,
                status=SyncStatus.FAILED,
                resources_synced=resources_synced,
                error_message=str(exc),
            )
            return SyncResult(
                job_id=job.id,
                provider=self.provider_type,
                status=SyncStatus.FAILED,
                resources_synced=resources_synced,
                errors=(*errors, str(exc)),
                completed_at=datetime.now(UTC),
            )

    async def backfill_history(
        self,
        request: SyncRequest,
        *,
        start_date: date,
        end_date: date,
    ) -> SyncResult:
        """Store missing metric days without downloading activity files again.

        Days that already have a raw row are skipped. The original payload stays.
        """
        errors: list[str] = []
        resources_synced: dict[ResourceType, int] = {}
        valid, auth_error = await self._token_store.validate_tokens()
        job = await self._sync_job_repo.create(request)
        if not valid:
            await self._sync_job_repo.complete(
                job.id,
                status=SyncStatus.FAILED,
                resources_synced={},
                error_message=auth_error,
            )
            return SyncResult(
                job_id=job.id,
                provider=self.provider_type,
                status=SyncStatus.FAILED,
                errors=(auth_error or "Garmin is not authenticated",),
                completed_at=datetime.now(UTC),
            )

        try:
            client = await GarminClient.from_token_path(self._token_store.token_path)
            for resource_type in request.resource_types:
                if resource_type == ResourceType.ACTIVITIES:
                    errors.append("Activity files are not part of metric backfill")
                    continue
                known = await self._raw_payload_repo.record_ids(
                    request.user_id,
                    DataProviderType.GARMIN.value,
                    resource_type.value,
                )
                records = await self._collect_backfill_records(
                    client, resource_type, start_date, end_date
                )
                saved = 0
                for record_id, payload in records:
                    if record_id in known:
                        continue
                    if await self._persist_payload(
                        request=request,
                        job_id=job.id,
                        resource_type=resource_type,
                        provider_record_id=record_id,
                        payload=payload,
                    ):
                        saved += 1
                        known.add(record_id)
                resources_synced[resource_type] = saved
            status = SyncStatus.COMPLETED if not errors else SyncStatus.FAILED
            await self._sync_job_repo.complete(
                job.id,
                status=status,
                resources_synced=resources_synced,
                error_message="; ".join(errors) if errors else None,
            )
            return SyncResult(
                job_id=job.id,
                provider=self.provider_type,
                status=status,
                resources_synced=resources_synced,
                errors=tuple(errors),
                completed_at=datetime.now(UTC),
            )
        except Exception as exc:
            pause_reason = garmin_auth_pause_reason(exc)
            if pause_reason:
                write_garmin_auth_pause(pause_reason)
            await self._sync_job_repo.complete(
                job.id,
                status=SyncStatus.FAILED,
                resources_synced=resources_synced,
                error_message=str(exc),
            )
            return SyncResult(
                job_id=job.id,
                provider=self.provider_type,
                status=SyncStatus.FAILED,
                resources_synced=resources_synced,
                errors=(*errors, str(exc)),
                completed_at=datetime.now(UTC),
            )

    async def _collect_backfill_records(
        self,
        client: GarminClient,
        resource_type: ResourceType,
        start_date: date,
        end_date: date,
    ) -> list[tuple[str, dict[str, Any]]]:
        if resource_type == ResourceType.HRV:
            records: list[tuple[str, dict[str, Any]]] = []
            chunks = chunk_dates(start_date, end_date, VERIFIED_RANGE_SPAN_DAYS)
            for chunk_start, chunk_end in chunks:
                payload = await client.get_hrv_data_range(chunk_start, chunk_end)
                records.extend(hrv_range_records(payload))
            return records
        return await self._collect_metric_records(client, resource_type, start_date, end_date)

    async def _remember_profile_timezone(self, client: GarminClient, user_id: UUID) -> None:
        """Prefer the IANA zone on the Garmin profile over the server clock."""
        try:
            profile_timezone = usable_timezone(await client.get_user_timezone())
        except Exception:
            logger.debug("Garmin profile timezone unavailable", exc_info=True)
            return
        if profile_timezone is None:
            return
        self._timezone = profile_timezone
        await self._connection_repo.remember_timezone(
            user_id,
            DataProviderType.GARMIN,
            profile_timezone,
        )

    def _resolve_date_window(self, request: SyncRequest) -> tuple[date, date]:
        end_date = today_local(self._timezone)
        if request.since is not None:
            start_date = request.since.date()
        elif request.full_sync:
            start_date = end_date - timedelta(days=365)
        else:
            start_date = end_date - timedelta(days=self._sync_days)
        return start_date, end_date

    async def _sync_resource(
        self,
        *,
        client: GarminClient,
        request: SyncRequest,
        job_id: UUID,
        resource_type: ResourceType,
        start_date: date,
        end_date: date,
    ) -> int:
        if resource_type == ResourceType.ACTIVITIES:
            return await self._sync_activities(client, request, job_id, start_date)
        if resource_type in _METRIC_RESOURCES:
            return await self._sync_metric_resource(
                client, request, job_id, resource_type, start_date, end_date
            )
        return await self._sync_daily_resource(
            client, request, job_id, resource_type, start_date, end_date
        )

    async def _sync_activities(
        self,
        client: GarminClient,
        request: SyncRequest,
        job_id: UUID,
        start_date: date,
    ) -> int:
        saved = 0
        start = 0
        limit = 50

        while True:
            activities = await client.get_activities(start=start, limit=limit)
            if not activities:
                break

            page_older = False
            for summary in activities:
                activity_id = str(summary.get("activityId") or summary.get("activity_id", ""))
                if not activity_id:
                    continue

                activity_date = self._parse_activity_date(summary)
                if activity_date is not None and activity_date < start_date:
                    # Newest-first search: this row and everything after it are
                    # outside the window, so do not download them.
                    page_older = True
                    break

                detail = await client.get_activity(activity_id)
                laps = await client.get_activity_laps(activity_id)
                if laps and isinstance(detail, dict):
                    detail = {**detail, "lapDTOs": laps}
                payload = {"summary": summary, "detail": detail}
                if await self._persist_payload(
                    request=request,
                    job_id=job_id,
                    resource_type=ResourceType.ACTIVITIES,
                    provider_record_id=activity_id,
                    payload=payload,
                ):
                    saved += 1

            if page_older or len(activities) < limit:
                break
            start += limit

        return saved

    async def _sync_daily_resource(
        self,
        client: GarminClient,
        request: SyncRequest,
        job_id: UUID,
        resource_type: ResourceType,
        start_date: date,
        end_date: date,
    ) -> int:
        saved = 0
        fetchers = {
            ResourceType.SLEEP: client.get_sleep_data,
            ResourceType.HRV: client.get_hrv_data,
            ResourceType.BODY_BATTERY: client.get_body_battery,
            ResourceType.TRAINING_READINESS: client.get_training_readiness,
            ResourceType.STRESS: client.get_stress_data,
            ResourceType.STEPS: client.get_daily_stats,
        }
        fetcher = fetchers[resource_type]

        for day in client.iter_dates(start_date, end_date):
            data = await fetcher(day)
            if not data:
                continue

            if await self._persist_payload(
                request=request,
                job_id=job_id,
                resource_type=resource_type,
                provider_record_id=day.isoformat(),
                payload={"date": day.isoformat(), "data": data},
            ):
                saved += 1

        return saved

    async def _sync_metric_resource(
        self,
        client: GarminClient,
        request: SyncRequest,
        job_id: UUID,
        resource_type: ResourceType,
        start_date: date,
        end_date: date,
    ) -> int:
        try:
            records = await self._collect_metric_records(
                client, resource_type, start_date, end_date
            )
        except Exception as exc:
            if garmin_auth_pause_reason(exc) or not is_missing_garmin_feature(exc):
                raise
            logger.info("Garmin resource %s is not available for this account", resource_type)
            return 0

        saved = 0
        for record_id, payload in records:
            if await self._persist_payload(
                request=request,
                job_id=job_id,
                resource_type=resource_type,
                provider_record_id=record_id,
                payload=payload,
            ):
                saved += 1
        return saved

    async def _collect_metric_records(
        self,
        client: GarminClient,
        resource_type: ResourceType,
        start_date: date,
        end_date: date,
    ) -> list[tuple[str, dict[str, Any]]]:
        if resource_type == ResourceType.ENDURANCE_SCORE:
            return await self._collect_chunked(
                start_date, end_date, client.get_endurance_score, endurance_records
            )
        if resource_type == ResourceType.HILL_SCORE:
            return await self._collect_chunked(
                start_date, end_date, client.get_hill_score, hill_records
            )
        if resource_type == ResourceType.RUNNING_TOLERANCE:
            return await self._collect_chunked(
                start_date, end_date, client.get_running_tolerance, tolerance_records
            )
        if resource_type == ResourceType.TRAINING_STATUS:
            return await self._collect_training_status(client, start_date, end_date)
        if resource_type == ResourceType.RACE_PREDICTIONS:
            return await self._collect_chunked(
                start_date, end_date, client.get_race_predictions, race_prediction_records
            )
        if resource_type == ResourceType.VO2_MAX:
            return await self._collect_vo2(client, start_date, end_date)
        if resource_type == ResourceType.HEAT_ACCLIMATION:
            return await self._collect_chunked(
                start_date, end_date, client.get_heat_altitude_acclimation, heat_records
            )
        if resource_type == ResourceType.RUNNING_ECONOMY:
            return await self._collect_chunked(
                start_date, end_date, client.get_running_economy, economy_records
            )
        if resource_type == ResourceType.STAMINA_CURVE:
            payload = await client.get_stamina_curve(end_date)
            return stamina_record(end_date, payload)
        if resource_type == ResourceType.POWER_CURVE:
            return await self._collect_power_curve(client, start_date, end_date)
        if resource_type == ResourceType.LACTATE_THRESHOLD:
            return await self._collect_lactate(client, start_date, end_date)
        if resource_type == ResourceType.RESPIRATION:
            return await self._collect_chunked(
                start_date, end_date, client.get_respiration_stats, respiration_records
            )
        if resource_type == ResourceType.SPO2_ACCLIMATION:
            return await self._collect_spo2(client, start_date, end_date)
        if resource_type == ResourceType.HEART_RATE:
            return await self._collect_chunked(
                start_date,
                end_date,
                client.get_heart_rate_stats,
                heart_rate_records,
                span_days=HEART_RATE_SPAN_DAYS,
            )
        if resource_type == ResourceType.WEIGHT:
            return await self._collect_chunked(
                start_date, end_date, client.get_weight_snapshot, weight_records
            )
        if resource_type == ResourceType.DEVICES:
            return await self._collect_devices(client)
        if resource_type == ResourceType.SOLAR_GAIN:
            return await self._collect_solar(client, start_date, end_date)
        if resource_type == ResourceType.TRAINING_PLAN:
            return await self._collect_training_plans(client)
        return []

    async def _collect_chunked(
        self,
        start_date: date,
        end_date: date,
        fetch,
        split,
        span_days: int = VERIFIED_RANGE_SPAN_DAYS,
    ) -> list[tuple[str, dict[str, Any]]]:
        records: list[tuple[str, dict[str, Any]]] = []
        for chunk_start, chunk_end in chunk_dates(start_date, end_date, span_days):
            payload = await fetch(chunk_start, chunk_end)
            records.extend(split(payload))
        return records

    async def _collect_training_status(
        self,
        client: GarminClient,
        start_date: date,
        end_date: date,
    ) -> list[tuple[str, dict[str, Any]]]:
        records: list[tuple[str, dict[str, Any]]] = []
        snapshot = await self._optional_metric(client.get_training_status(end_date))
        for chunk_start, chunk_end in chunk_dates(
            start_date, end_date, VERIFIED_RANGE_SPAN_DAYS
        ):
            weekly = await client.get_weekly_training_status(chunk_start, chunk_end)
            chunk_records = training_status_records(
                weekly,
                snapshot if chunk_end == end_date else None,
            )
            records.extend(chunk_records)
        if records:
            return records
        return training_status_records({}, snapshot)

    async def _collect_vo2(
        self,
        client: GarminClient,
        start_date: date,
        end_date: date,
    ) -> list[tuple[str, dict[str, Any]]]:
        latest = await self._optional_metric(client.get_max_metrics_latest(end_date))
        ranged: list[Any] = []
        for chunk_start, chunk_end in chunk_dates(
            start_date, end_date, VERIFIED_RANGE_SPAN_DAYS
        ):
            chunk = await self._optional_metric(
                client.get_max_metrics_range(chunk_start, chunk_end)
            )
            if isinstance(chunk, list):
                ranged.extend(chunk)
        return vo2_records(latest, ranged)

    async def _collect_power_curve(
        self,
        client: GarminClient,
        start_date: date,
        end_date: date,
    ) -> list[tuple[str, dict[str, Any]]]:
        records: list[tuple[str, dict[str, Any]]] = []
        for sport in POWER_CURVE_SPORTS:
            try:
                payload = await client.get_power_curve(start_date, end_date, sport)
            except Exception as exc:
                if garmin_auth_pause_reason(exc):
                    raise
                if is_unsupported_power_sport(exc):
                    logger.info("Garmin power curve is not available for %s", sport)
                    continue
                raise
            records.extend(power_curve_record(sport, end_date, payload))
        return records

    async def _collect_lactate(
        self,
        client: GarminClient,
        start_date: date,
        end_date: date,
    ) -> list[tuple[str, dict[str, Any]]]:
        latest = await self._optional_metric(client.get_lactate_threshold_latest())
        ranged_parts: list[dict[str, Any]] = []
        for chunk_start, chunk_end in chunk_dates(
            start_date, end_date, VERIFIED_RANGE_SPAN_DAYS
        ):
            chunk = await self._optional_metric(
                client.get_lactate_threshold_range(chunk_start, chunk_end)
            )
            if isinstance(chunk, dict):
                ranged_parts.append(chunk)
        merged: dict[str, list[Any]] = {}
        for part in ranged_parts:
            for key, series in part.items():
                if isinstance(series, list):
                    merged.setdefault(key, []).extend(series)
        return lactate_records(latest, merged)

    async def _collect_spo2(
        self,
        client: GarminClient,
        start_date: date,
        end_date: date,
    ) -> list[tuple[str, dict[str, Any]]]:
        records: list[tuple[str, dict[str, Any]]] = []
        for day in client.iter_dates(start_date, end_date):
            payload = await self._optional_metric(client.get_spo2_acclimation(day))
            records.extend(spo2_record(day, payload))
        return records

    async def _collect_training_plans(
        self, client: GarminClient
    ) -> list[tuple[str, dict[str, Any]]]:
        today = today_local(self._timezone)
        # Active-on-date misses a plan whose start date is still tomorrow.
        # The plan list includes scheduled Coach plans before they begin.
        listed = await self._optional_metric(client.get_training_plans(limit=20))
        plans = listed.get("trainingPlanList") if isinstance(listed, dict) else None
        if not isinstance(plans, list):
            return []
        plans = [plan for plan in plans if _plan_still_relevant(plan, today)]

        records: list[tuple[str, dict[str, Any]]] = []
        for plan in plans:
            if not isinstance(plan, dict) or plan.get("trainingPlanId") is None:
                continue
            plan_id = plan["trainingPlanId"]
            if plan.get("trainingPlanCategory") == "FBT_ADAPTIVE":
                detail = await self._optional_metric(client.get_adaptive_training_plan(plan_id))
            else:
                detail = await self._optional_metric(client.get_training_plan(plan_id))
            payload = detail if isinstance(detail, dict) and detail.get("trainingPlanId") else plan
            records.append((str(plan_id), payload))
        return records

    async def _collect_devices(self, client: GarminClient) -> list[tuple[str, dict[str, Any]]]:
        devices = await client.get_devices()
        primary = await self._optional_metric(client.get_primary_training_device())
        last_used = await self._optional_metric(client.get_device_last_used())
        return device_inventory_record(devices, primary, last_used)

    async def _collect_solar(
        self,
        client: GarminClient,
        start_date: date,
        end_date: date,
    ) -> list[tuple[str, dict[str, Any]]]:
        devices = await self._optional_metric(client.get_devices())
        records: list[tuple[str, dict[str, Any]]] = []
        for device_id in device_ids(devices):
            for chunk_start, chunk_end in chunk_dates(
                start_date, end_date, VERIFIED_RANGE_SPAN_DAYS
            ):
                try:
                    payload = await client.get_device_solar_gain(device_id, chunk_start, chunk_end)
                except Exception as exc:
                    if garmin_auth_pause_reason(exc):
                        raise
                    if garmin_http_status(exc) in {400, 404}:
                        logger.info("Garmin solar gain is not available for one registered device")
                        continue
                    raise
                records.extend(solar_records(device_id, payload))
        return records

    async def _optional_metric(self, awaitable: Any) -> Any:
        try:
            return await awaitable
        except Exception as exc:
            if garmin_auth_pause_reason(exc):
                raise
            if is_missing_garmin_feature(exc):
                return None
            raise

    async def _persist_payload(
        self,
        *,
        request: SyncRequest,
        job_id: UUID,
        resource_type: ResourceType,
        provider_record_id: str,
        payload: dict[str, Any],
    ) -> bool:
        content_hash = payload_content_hash(payload)
        existing = await self._raw_payload_repo.get_by_hash(request.user_id, content_hash)
        if existing is not None:
            return False

        await self._raw_payload_repo.save(
            RawPayload(
                user_id=request.user_id,
                provider=DataProviderType.GARMIN,
                resource_type=resource_type,
                provider_record_id=provider_record_id,
                payload=payload,
                content_hash=content_hash,
                fetched_at=datetime.now(UTC),
                sync_job_id=job_id,
            )
        )
        return True

    def _parse_activity_date(self, summary: dict[str, Any]) -> date | None:
        return garmin_activity_local_date(summary, timezone=self._timezone)
