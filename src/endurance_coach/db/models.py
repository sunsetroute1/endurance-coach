"""SQLAlchemy ORM models."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from endurance_coach.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from endurance_coach.domain.enums import DataProviderType, MetricFamily, ResourceType, SyncStatus


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))

    provider_connections: Mapped[list[ProviderConnection]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sync_jobs: Mapped[list[SyncJob]] = relationship(back_populates="user")
    raw_payloads: Mapped[list[RawPayloadRecord]] = relationship(back_populates="user")


class ProviderConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_provider_connection_user_provider"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    token_reference: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, str] | None] = mapped_column(JSONB)

    user: Mapped[User] = relationship(back_populates="provider_connections")


class SyncJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sync_jobs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=SyncStatus.PENDING, nullable=False)
    resource_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    cursor: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resources_synced: Mapped[dict[str, int] | None] = mapped_column(JSONB)

    user: Mapped[User] = relationship(back_populates="sync_jobs")
    raw_payloads: Mapped[list[RawPayloadRecord]] = relationship(back_populates="sync_job")


class RawPayloadRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "raw_payloads"
    __table_args__ = (
        UniqueConstraint("user_id", "content_hash", name="uq_raw_payload_user_hash"),
        Index("ix_raw_payloads_user_resource", "user_id", "resource_type"),
        Index("ix_raw_payloads_provider_record", "provider", "provider_record_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    sync_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sync_jobs.id", ondelete="SET NULL"),
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="raw_payloads")
    sync_job: Mapped[SyncJob | None] = relationship(back_populates="raw_payloads")


class ActivityRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "provider_record_id", name="uq_activity_provider"),
        Index("ix_activities_user_started", "user_id", "started_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_record_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_payload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_payloads.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_meters: Mapped[float | None] = mapped_column(Float)
    avg_heart_rate: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    avg_pace_sec_per_km: Mapped[float | None] = mapped_column(Float)
    elevation_gain_meters: Mapped[float | None] = mapped_column(Float)
    training_load: Mapped[float | None] = mapped_column(Float)


class SleepRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sleep_records"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "sleep_date", name="uq_sleep_user_date"),
        Index("ix_sleep_user_date", "user_id", "sleep_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    sleep_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_payload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_payloads.id", ondelete="RESTRICT"),
        nullable=False,
    )
    total_sleep_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    deep_sleep_seconds: Mapped[int | None] = mapped_column(Integer)
    rem_sleep_seconds: Mapped[int | None] = mapped_column(Integer)
    light_sleep_seconds: Mapped[int | None] = mapped_column(Integer)
    awake_seconds: Mapped[int | None] = mapped_column(Integer)
    sleep_score: Mapped[int | None] = mapped_column(Integer)


class HRVRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "hrv_records"
    __table_args__ = (Index("ix_hrv_user_recorded", "user_id", "recorded_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_payload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_payloads.id", ondelete="RESTRICT"),
        nullable=False,
    )
    hrv_ms: Mapped[float] = mapped_column(Float, nullable=False)
    resting_heart_rate: Mapped[int | None] = mapped_column(Integer)
    baseline_ms: Mapped[float | None] = mapped_column(Float)


class BodyBatteryRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "body_battery_records"
    __table_args__ = (Index("ix_body_battery_user_recorded", "user_id", "recorded_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_payload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_payloads.id", ondelete="RESTRICT"),
        nullable=False,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    charged: Mapped[int | None] = mapped_column(Integer)
    drained: Mapped[int | None] = mapped_column(Integer)


class TrainingReadinessRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "training_readiness_records"
    __table_args__ = (Index("ix_readiness_user_recorded", "user_id", "recorded_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_payload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_payloads.id", ondelete="RESTRICT"),
        nullable=False,
    )
    readiness_score: Mapped[int] = mapped_column(Integer, nullable=False)
    hrv_component: Mapped[int | None] = mapped_column(Integer)
    sleep_component: Mapped[int | None] = mapped_column(Integer)
    recovery_component: Mapped[int | None] = mapped_column(Integer)


class StressRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stress_records"
    __table_args__ = (Index("ix_stress_user_recorded", "user_id", "recorded_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_payload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_payloads.id", ondelete="RESTRICT"),
        nullable=False,
    )
    avg_stress: Mapped[int] = mapped_column(Integer, nullable=False)
    max_stress: Mapped[int | None] = mapped_column(Integer)


class StepsRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "steps_records"
    __table_args__ = (
        Index("ix_steps_user_date", "user_id", "step_date"),
        Index(
            "uq_steps_user_provider_date",
            "user_id",
            "provider",
            "step_date",
            unique=True,
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    step_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_payload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_payloads.id", ondelete="RESTRICT"),
        nullable=False,
    )
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    step_goal: Mapped[int | None] = mapped_column(Integer)
    distance_meters: Mapped[float | None] = mapped_column(Float)


class RunningDynamicsRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "running_dynamics_records"
    __table_args__ = (Index("ix_running_dynamics_activity", "activity_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("activities.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_payload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("raw_payloads.id", ondelete="RESTRICT"),
        nullable=False,
    )
    avg_cadence: Mapped[float | None] = mapped_column(Float)
    avg_vertical_oscillation_mm: Mapped[float | None] = mapped_column(Float)
    avg_ground_contact_time_ms: Mapped[float | None] = mapped_column(Float)
    avg_stride_length_m: Mapped[float | None] = mapped_column(Float)


class ComputedMetricRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "computed_metrics"
    __table_args__ = (
        Index("ix_computed_metrics_user_family", "user_id", "family", "as_of"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    family: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[str] = mapped_column(String(16), default="1.0.0", nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)


# Re-export enums for Alembic autogenerate awareness
__all__ = [
    "ActivityRecord",
    "BodyBatteryRecord",
    "ComputedMetricRecord",
    "DataProviderType",
    "HRVRecord",
    "MetricFamily",
    "ProviderConnection",
    "RawPayloadRecord",
    "ResourceType",
    "RunningDynamicsRecord",
    "SleepRecord",
    "StepsRecord",
    "StressRecord",
    "SyncJob",
    "SyncStatus",
    "TrainingReadinessRecord",
    "User",
]
