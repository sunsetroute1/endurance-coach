"""Normalizer interfaces for the processor layer."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from endurance_coach.domain.enums import DataProviderType, ResourceType
from endurance_coach.domain.models import (
    NormalizedActivity,
    NormalizedBodyBattery,
    NormalizedHRV,
    NormalizedReadiness,
    NormalizedRunningDynamics,
    NormalizedSleep,
    NormalizedStress,
    RawPayload,
)


class NormalizationResult(Protocol):
    """Marker for typed normalization outputs."""

    resource_type: ResourceType


class ActivityNormalizer(Protocol):
    async def normalize(
        self,
        payload: RawPayload,
    ) -> NormalizedActivity: ...

    def supports(self, provider: DataProviderType) -> bool: ...


class SleepNormalizer(Protocol):
    async def normalize(
        self,
        payload: RawPayload,
    ) -> NormalizedSleep: ...

    def supports(self, provider: DataProviderType) -> bool: ...


class HRVNormalizer(Protocol):
    async def normalize(
        self,
        payload: RawPayload,
    ) -> NormalizedHRV: ...

    def supports(self, provider: DataProviderType) -> bool: ...


class ReadinessNormalizer(Protocol):
    async def normalize(
        self,
        payload: RawPayload,
    ) -> NormalizedReadiness: ...

    def supports(self, provider: DataProviderType) -> bool: ...


class BodyBatteryNormalizer(Protocol):
    async def normalize(
        self,
        payload: RawPayload,
    ) -> NormalizedBodyBattery: ...

    def supports(self, provider: DataProviderType) -> bool: ...


class StressNormalizer(Protocol):
    async def normalize(
        self,
        payload: RawPayload,
    ) -> NormalizedStress: ...

    def supports(self, provider: DataProviderType) -> bool: ...


class RunningDynamicsNormalizer(Protocol):
    async def normalize(
        self,
        payload: RawPayload,
        activity_id: UUID,
    ) -> NormalizedRunningDynamics: ...

    def supports(self, provider: DataProviderType) -> bool: ...


class ProcessorPipeline(Protocol):
    """Orchestrates normalization for unprocessed raw payloads."""

    async def process_pending(
        self,
        user_id: UUID,
        resource_type: ResourceType,
        limit: int = 100,
    ) -> int: ...
