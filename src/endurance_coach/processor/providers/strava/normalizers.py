"""Strava activity normalizer."""

from __future__ import annotations

from typing import Any

from endurance_coach.domain.enums import DataProviderType
from endurance_coach.domain.models import NormalizedActivity, RawPayload
from endurance_coach.processor.parsing import (
    as_float,
    as_int,
    pace_from_distance_duration,
    parse_datetime,
)


class StravaActivityNormalizer:
    def supports(self, provider: DataProviderType) -> bool:
        return provider == DataProviderType.STRAVA

    async def normalize(self, payload: RawPayload) -> NormalizedActivity:
        root = payload.payload
        summary = root.get("summary", root)
        detail = root.get("detail", {})
        merged: dict[str, Any] = {**summary, **detail} if isinstance(detail, dict) else summary

        started_at = parse_datetime(merged.get("start_date_local") or merged.get("start_date"))
        if started_at is None:
            raise ValueError("Strava activity payload missing start date")

        duration_seconds = as_int(merged.get("moving_time") or merged.get("elapsed_time")) or 0
        distance_meters = as_float(merged.get("distance"))
        pace = pace_from_distance_duration(distance_meters, duration_seconds)
        activity_type = str(merged.get("sport_type") or merged.get("type") or "unknown")

        if payload.id is None:
            raise ValueError("Raw payload id is required for normalization")

        return NormalizedActivity(
            user_id=payload.user_id,
            provider=payload.provider,
            provider_record_id=payload.provider_record_id,
            name=str(merged.get("name") or "Untitled Activity"),
            activity_type=activity_type,
            started_at=started_at,
            duration_seconds=duration_seconds,
            distance_meters=distance_meters,
            avg_heart_rate=as_int(merged.get("average_heartrate")),
            max_heart_rate=as_int(merged.get("max_heartrate")),
            avg_pace_sec_per_km=pace,
            elevation_gain_meters=as_float(merged.get("total_elevation_gain")),
            training_load=as_float(merged.get("suffer_score")),
            source_payload_id=payload.id,
        )
