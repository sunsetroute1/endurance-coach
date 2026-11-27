"""Incremental activity-detail collection without a database."""

from uuid import uuid4

import pytest

from endurance_coach.collector.providers.garmin.activity_detail_sync import (
    DetailJob,
    GarminActivityDetailCollector,
)


class _Client:
    def __init__(self, payloads: dict[str, dict], *, fail: set[str] | None = None) -> None:
        self.payloads = payloads
        self.fail = fail or set()
        self.calls: list[str] = []

    async def get_activity_details(self, activity_id: str, *, maxchart: int = 20000) -> dict:
        self.calls.append(activity_id)
        if activity_id in self.fail:
            raise RuntimeError("429 too many requests")
        return self.payloads[activity_id]


class _Store:
    def __init__(self) -> None:
        self.status: dict[str, str] = {}
        self.raw: dict[str, tuple] = {}
        self.samples: dict[str, list] = {}

    async def get_status(self, user_id, provider_activity_id: str) -> str | None:
        return self.status.get(provider_activity_id)

    async def get_raw(self, user_id, provider_activity_id: str):
        return self.raw.get(provider_activity_id)

    async def save_raw(self, job: DetailJob, payload: dict):
        source_id = uuid4()
        self.raw[job.provider_activity_id] = (source_id, payload)
        return source_id

    async def replace_samples(self, job: DetailJob, source_payload_id, samples: list) -> None:
        self.samples[job.provider_activity_id] = samples

    async def save_status(
        self,
        job: DetailJob,
        *,
        status: str,
        sample_count: int,
        **_kwargs,
    ) -> None:
        self.status[job.provider_activity_id] = status
        self.samples.setdefault(job.provider_activity_id, [])
        if status != "collected":
            self.samples[job.provider_activity_id] = []


def _chart(heart: int | None) -> dict:
    metrics = [1_700_000_000_000, 0, heart]
    return {
        "metricDescriptors": [
            {"metricsIndex": 0, "key": "directTimestamp", "unit": {"unitKey": "gmt"}},
            {
                "metricsIndex": 1,
                "key": "sumDuration",
                "unit": {"unitKey": "second", "factor": 1000},
            },
            {"metricsIndex": 2, "key": "directHeartRate", "unit": {"unitKey": "bpm", "factor": 1}},
        ],
        "activityDetailMetrics": [{"metrics": metrics}, {"metrics": "bad"}],
    }


def _job(activity_id: str) -> DetailJob:
    return DetailJob(user_id=uuid4(), activity_id=uuid4(), provider_activity_id=activity_id)


@pytest.mark.asyncio
async def test_second_pass_skips_collected_and_unsupported() -> None:
    client = _Client({"rich": _chart(140), "old": _chart(None)})
    store = _Store()
    pauses: list[float] = []

    async def _sleep(seconds: float) -> None:
        pauses.append(seconds)

    collector = GarminActivityDetailCollector(client, store, pause_seconds=1, sleeper=_sleep)
    jobs = [_job("rich"), _job("old")]
    first = await collector.collect(jobs)
    assert first.collected == 1
    assert first.unsupported == 1
    assert client.calls == ["rich", "old"]
    assert pauses == [1]
    second = await collector.collect(jobs)
    assert second.skipped == 2
    assert second.downloaded == 0
    assert client.calls == ["rich", "old"]


@pytest.mark.asyncio
async def test_failed_activity_retries_until_rate_limit_stops_the_batch() -> None:
    charts = {"ok": _chart(120), "blocked": _chart(120), "later": _chart(120)}
    client = _Client(charts, fail={"blocked", "later"})
    store = _Store()
    collector = GarminActivityDetailCollector(client, store, pause_seconds=0)
    jobs = [_job("ok"), _job("blocked"), _job("later")]
    result = await collector.collect(jobs)
    assert result.collected == 1
    assert result.failed == 1
    assert result.stopped_reason is not None
    assert "later" not in client.calls
    assert store.status["blocked"] == "failed"
    client.fail.remove("blocked")
    retried = await collector.collect([jobs[1]])
    assert retried.collected == 1
    assert store.status["blocked"] == "collected"


@pytest.mark.asyncio
async def test_stored_raw_chart_is_not_downloaded_again() -> None:
    client = _Client({"rich": _chart(130)})
    store = _Store()
    store.raw["rich"] = (uuid4(), _chart(130))
    collector = GarminActivityDetailCollector(client, store, pause_seconds=0)
    result = await collector.collect([_job("rich")])
    assert result.collected == 1
    assert result.downloaded == 0
    assert client.calls == []
