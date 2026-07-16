"""Pydantic domain models shared across layers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from endurance_coach.domain.enums import (
    DataProviderType,
    InjuryRiskLevel,
    MetricFamily,
    ResourceType,
    SyncStatus,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)


# --- Collector ---


class TokenReference(DomainModel):
    """Opaque reference to provider credentials — never contains secrets."""

    provider: DataProviderType
    reference_path: str
    expires_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ProviderSetupInstructions(DomainModel):
    provider: DataProviderType
    summary: str
    steps: tuple[str, ...]
    verify_command: str | None = None


class SyncRequest(DomainModel):
    user_id: UUID
    provider: DataProviderType
    resource_types: tuple[ResourceType, ...]
    since: datetime | None = None
    full_sync: bool = False


class SyncResult(DomainModel):
    job_id: UUID
    provider: DataProviderType
    status: SyncStatus
    resources_synced: dict[ResourceType, int] = Field(default_factory=dict)
    errors: tuple[str, ...] = ()
    completed_at: datetime | None = None


class RawPayload(DomainModel):
    id: UUID | None = None
    user_id: UUID
    provider: DataProviderType
    resource_type: ResourceType
    provider_record_id: str
    payload: dict[str, Any]
    content_hash: str
    fetched_at: datetime
    sync_job_id: UUID | None = None


# --- Processor (normalized records) ---


class NormalizedActivity(DomainModel):
    id: UUID | None = None
    user_id: UUID
    provider: DataProviderType
    provider_record_id: str
    name: str
    activity_type: str
    started_at: datetime
    duration_seconds: int
    distance_meters: float | None = None
    avg_heart_rate: int | None = None
    max_heart_rate: int | None = None
    avg_pace_sec_per_km: float | None = None
    elevation_gain_meters: float | None = None
    training_load: float | None = None
    source_payload_id: UUID


class NormalizedSleep(DomainModel):
    id: UUID | None = None
    user_id: UUID
    provider: DataProviderType
    sleep_date: date
    total_sleep_seconds: int
    deep_sleep_seconds: int | None = None
    rem_sleep_seconds: int | None = None
    light_sleep_seconds: int | None = None
    awake_seconds: int | None = None
    sleep_score: int | None = None
    source_payload_id: UUID


class NormalizedHRV(DomainModel):
    id: UUID | None = None
    user_id: UUID
    provider: DataProviderType
    recorded_at: datetime
    hrv_ms: float
    resting_heart_rate: int | None = None
    baseline_ms: float | None = None
    source_payload_id: UUID


class NormalizedReadiness(DomainModel):
    id: UUID | None = None
    user_id: UUID
    provider: DataProviderType
    recorded_at: datetime
    readiness_score: int
    hrv_component: int | None = None
    sleep_component: int | None = None
    recovery_component: int | None = None
    source_payload_id: UUID


class NormalizedBodyBattery(DomainModel):
    id: UUID | None = None
    user_id: UUID
    provider: DataProviderType
    recorded_at: datetime
    level: int
    charged: int | None = None
    drained: int | None = None
    source_payload_id: UUID


class NormalizedStress(DomainModel):
    id: UUID | None = None
    user_id: UUID
    provider: DataProviderType
    recorded_at: datetime
    avg_stress: int
    max_stress: int | None = None
    source_payload_id: UUID


class NormalizedSteps(DomainModel):
    id: UUID | None = None
    user_id: UUID
    provider: DataProviderType
    step_date: date
    total_steps: int
    step_goal: int | None = None
    distance_meters: float | None = None
    source_payload_id: UUID


class NormalizedRunningDynamics(DomainModel):
    id: UUID | None = None
    user_id: UUID
    provider: DataProviderType
    activity_id: UUID
    avg_cadence: float | None = None
    avg_vertical_oscillation_mm: float | None = None
    avg_ground_contact_time_ms: float | None = None
    avg_stride_length_m: float | None = None
    source_payload_id: UUID


# --- Analytics ---


class MetricValue(DomainModel):
    key: str
    value: float
    unit: str
    computed_at: datetime


class MetricSnapshot(DomainModel):
    user_id: UUID
    family: MetricFamily
    as_of: datetime
    metrics: tuple[MetricValue, ...]


class LoadMetrics(DomainModel):
    ctl: float
    atl: float
    tsb: float
    acwr: float
    weekly_load: float
    monotony: float
    strain: float


class RecoveryMetrics(DomainModel):
    recovery_score: float
    fatigue_score: float
    sleep_debt_hours: float
    hrv_deviation_pct: float


class InjuryRiskAssessment(DomainModel):
    level: InjuryRiskLevel
    score: float
    factors: tuple[str, ...]


# --- Coach ---


class CoachRequest(DomainModel):
    user_id: UUID
    intent: str
    context_date: date | None = None


class CoachRecommendation(DomainModel):
    category: str
    action: str
    rationale: str
    metric_citations: tuple[str, ...]


class CoachResponse(DomainModel):
    explanation: str
    recommendations: tuple[CoachRecommendation, ...]
    metrics_used: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)
