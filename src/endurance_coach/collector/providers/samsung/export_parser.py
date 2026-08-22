"""Parse Samsung Health personal data export CSV/JSON files."""

from __future__ import annotations

import csv
import json
import re
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from endurance_coach.collector.providers.samsung.import_service import SamsungImportRecord
from endurance_coach.domain.enums import ResourceType

SLEEP_STAGE_SECONDS = {
    "40001": "awake_seconds",
    "40002": "light_sleep_seconds",
    "40003": "deep_sleep_seconds",
    "40004": "rem_sleep_seconds",
}

EXERCISE_TYPE_NAMES: dict[str, str] = {
    "1001": "walking",
    "1002": "running",
    "1003": "cycling",
    "1004": "elliptical",
    "1005": "treadmill",
    "1006": "hiking",
    "1007": "swimming",
    "1008": "yoga",
    "1009": "circuit_training",
    "1010": "bicycle",
    "1011": "dancing",
    "1013": "weight_training",
    "1014": "basketball",
    "1015": "soccer",
    "1018": "tennis",
    "1020": "badminton",
    "1021": "baseball",
    "1022": "golf",
    "1023": "volleyball",
    "1024": "rock_climbing",
    "13001": "trail_running",
}


def find_export_dir(root: Path) -> Path:
    """Return the newest samsunghealth_* export folder under root."""
    return iter_export_dirs(root)[-1]


def iter_export_dirs(root: Path) -> list[Path]:
    """Return all samsunghealth_* export folders under root, oldest first."""
    candidates = sorted(path for path in root.glob("**/samsunghealth_*") if path.is_dir())
    if not candidates:
        raise FileNotFoundError(f"No samsunghealth_* export folder under {root}")
    return candidates


def read_samsung_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 3:
        return []
    header = rows[1]
    records: list[dict[str, str]] = []
    for row in rows[2:]:
        if not row or not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * (len(header) - len(row))
        records.append(dict(zip(header, padded, strict=False)))
    return records


EXERCISE_PREFIX = "com.samsung.health.exercise."


def _exercise_location_path(base: Path, row: dict[str, str]) -> Path | None:
    rel = row.get(f"{EXERCISE_PREFIX}location_data", "").strip()
    if not rel:
        return None
    name = rel.split("/")[-1]
    candidate = base / "jsons" / "com.samsung.shealth.exercise" / name[0].lower() / name
    if candidate.exists():
        return candidate
    return next((path for path in base.rglob(name)), None)


def elevation_gain_from_location(path: Path) -> float | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return None
    alts = [float(point["altitude"]) for point in data if point.get("altitude") is not None]
    if len(alts) < 2:
        return None
    gain = sum(max(0.0, alts[index + 1] - alts[index]) for index in range(len(alts) - 1))
    return gain if gain > 0 else None


def elevation_gain_from_exercise_row(base: Path, row: dict[str, str]) -> float | None:
    csv_gain = _float(row.get(f"{EXERCISE_PREFIX}altitude_gain"))
    if csv_gain is not None and csv_gain > 0:
        return csv_gain

    location_path = _exercise_location_path(base, row)
    if location_path is not None:
        track_gain = elevation_gain_from_location(location_path)
        if track_gain is not None and track_gain > 0:
            return round(track_gain, 1)

    min_alt = _float(row.get(f"{EXERCISE_PREFIX}min_altitude"))
    max_alt = _float(row.get(f"{EXERCISE_PREFIX}max_altitude"))
    if min_alt is not None and max_alt is not None and max_alt > min_alt:
        return round(max_alt - min_alt, 1)

    return None


def _parse_timestamp(value: str, time_offset: str | None = None) -> datetime | None:
    if not value or not value.strip():
        return None
    text = value.strip()
    try:
        if text.isdigit():
            epoch_ms = int(text)
            if epoch_ms > 1_000_000_000_000:
                epoch_ms //= 1000
            return datetime.fromtimestamp(epoch_ms, tz=UTC)
        normalized = text.replace(".000", "")
        if "T" not in normalized and " " in normalized:
            normalized = normalized.replace(" ", "T", 1)
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None and time_offset:
            offset = time_offset.replace("UTC", "")
            if offset:
                sign = 1 if offset.startswith("+") else -1
                hours = int(offset[1:3])
                minutes = int(offset[4:6]) if len(offset) >= 6 else 0
                delta = timedelta(hours=hours, minutes=minutes)
                tz = ZoneInfo("UTC")
                parsed = parsed.replace(tzinfo=tz) - sign * delta
                return parsed.astimezone(UTC)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _find_csv(base: Path, stem: str) -> Path | None:
    pattern = re.compile(rf"^{re.escape(stem)}\.\d+\.csv$")
    matches = sorted(path for path in base.glob(f"{stem}*.csv") if pattern.match(path.name))
    return matches[-1] if matches else None


def _load_hrv_binning(base: Path, binning_ref: str) -> list[dict[str, Any]]:
    if not binning_ref:
        return []
    rel = Path("jsons") / "com.samsung.health.hrv" / binning_ref[0].lower() / binning_ref
    path = base / rel
    if not path.exists():
        path = base / binning_ref
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _aggregate_sleep_stages(base: Path) -> dict[str, dict[str, int]]:
    stage_path = _find_csv(base, "com.samsung.health.sleep_stage")
    if stage_path is None:
        return {}

    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "awake_seconds": 0,
            "light_sleep_seconds": 0,
            "deep_sleep_seconds": 0,
            "rem_sleep_seconds": 0,
        }
    )
    for row in read_samsung_csv(stage_path):
        sleep_id = row.get("sleep_id", "")
        stage = row.get("stage", "")
        start = _parse_timestamp(row.get("start_time", ""), row.get("time_offset"))
        end = _parse_timestamp(row.get("end_time", ""), row.get("time_offset"))
        if not sleep_id or not start or not end:
            continue
        seconds = max(int((end - start).total_seconds()), 0)
        field = SLEEP_STAGE_SECONDS.get(stage)
        if field is None:
            continue
        totals[sleep_id][field] += seconds
    return totals


def _aggregate_sleep_sessions(base: Path) -> dict[str, dict[str, Any]]:
    """Build per-session timing and stage totals from sleep_stage rows."""
    stage_path = _find_csv(base, "com.samsung.health.sleep_stage")
    if stage_path is None:
        return {}

    sessions: dict[str, dict[str, Any]] = {}
    for row in read_samsung_csv(stage_path):
        sleep_id = row.get("sleep_id", "")
        stage = row.get("stage", "")
        start = _parse_timestamp(row.get("start_time", ""), row.get("time_offset"))
        end = _parse_timestamp(row.get("end_time", ""), row.get("time_offset"))
        if not sleep_id or not start or not end:
            continue
        seconds = max(int((end - start).total_seconds()), 0)
        session = sessions.setdefault(
            sleep_id,
            {
                "start": start,
                "end": end,
                "awake_seconds": 0,
                "light_sleep_seconds": 0,
                "deep_sleep_seconds": 0,
                "rem_sleep_seconds": 0,
            },
        )
        if start < session["start"]:
            session["start"] = start
        if end > session["end"]:
            session["end"] = end
        field = SLEEP_STAGE_SECONDS.get(stage)
        if field is not None:
            session[field] += seconds
    return sessions


def _merge_sleep_day(existing: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "start_time": existing.get("start_time") or session["start"].isoformat(),
        "end_time": session["end"].isoformat(),
        "awake_seconds": existing.get("awake_seconds", 0) + session["awake_seconds"],
        "light_sleep_seconds": existing.get("light_sleep_seconds", 0) + session["light_sleep_seconds"],
        "deep_sleep_seconds": existing.get("deep_sleep_seconds", 0) + session["deep_sleep_seconds"],
        "rem_sleep_seconds": existing.get("rem_sleep_seconds", 0) + session["rem_sleep_seconds"],
        "sleep_score": existing.get("sleep_score"),
    }
    if session["start"].isoformat() < merged["start_time"]:
        merged["start_time"] = session["start"].isoformat()
    asleep = (
        merged["light_sleep_seconds"]
        + merged["deep_sleep_seconds"]
        + merged["rem_sleep_seconds"]
    )
    merged["total_sleep_seconds"] = asleep
    return merged


def _sleep_records_from_stages(
    base: Path,
    *,
    start_date: date,
    end_date: date,
) -> dict[date, dict[str, Any]]:
    """Return one merged sleep payload per wake date derived from sleep_stage."""
    by_date: dict[date, dict[str, Any]] = {}
    for session in _aggregate_sleep_sessions(base).values():
        end_time = session["end"]
        sleep_date = end_time.date()
        if sleep_date < start_date or sleep_date > end_date:
            continue
        asleep = (
            session["light_sleep_seconds"]
            + session["deep_sleep_seconds"]
            + session["rem_sleep_seconds"]
        )
        if asleep <= 0:
            continue
        payload = {
            "sleep_date": sleep_date.isoformat(),
            "start_time": session["start"].isoformat(),
            "end_time": end_time.isoformat(),
            "total_sleep_seconds": asleep,
            "deep_sleep_seconds": session["deep_sleep_seconds"],
            "rem_sleep_seconds": session["rem_sleep_seconds"],
            "light_sleep_seconds": session["light_sleep_seconds"],
            "awake_seconds": session["awake_seconds"],
            "sleep_score": None,
        }
        if sleep_date in by_date:
            by_date[sleep_date] = _merge_sleep_day(by_date[sleep_date], session)
        else:
            by_date[sleep_date] = payload
    return by_date


def _sleep_records_from_sleep_csv(
    base: Path,
    stage_totals: dict[str, dict[str, int]],
    *,
    start_date: date,
    end_date: date,
) -> dict[date, dict[str, Any]]:
    """Parse com.samsung.shealth.sleep rows (prefixed columns, ~989 sessions)."""
    sleep_path = _find_csv(base, "com.samsung.shealth.sleep")
    if sleep_path is None:
        return {}

    prefix = "com.samsung.health.sleep."
    by_date: dict[date, dict[str, Any]] = {}
    for row in read_samsung_csv(sleep_path):
        end_time = _parse_timestamp(row.get(f"{prefix}end_time", ""), row.get(f"{prefix}time_offset"))
        start_time = _parse_timestamp(row.get(f"{prefix}start_time", ""), row.get(f"{prefix}time_offset"))
        if end_time is None or start_time is None:
            continue
        sleep_date = end_time.date()
        if sleep_date < start_date or sleep_date > end_date:
            continue

        sleep_id = row.get(f"{prefix}datauuid", "")
        stages = stage_totals.get(sleep_id, {})
        asleep = (
            stages.get("light_sleep_seconds", 0)
            + stages.get("deep_sleep_seconds", 0)
            + stages.get("rem_sleep_seconds", 0)
        )
        if asleep <= 0:
            asleep = sum(filter(None, [_minutes(row, key) for key in ("factor_02", "factor_03", "factor_04")])) or 0
        if asleep <= 0:
            asleep = max(int((end_time - start_time).total_seconds()) - stages.get("awake_seconds", 0), 0)
        if asleep <= 0:
            continue

        payload = {
            "sleep_date": sleep_date.isoformat(),
            "start_time": row.get(f"{prefix}start_time"),
            "end_time": row.get(f"{prefix}end_time"),
            "total_sleep_seconds": asleep,
            "deep_sleep_seconds": stages.get("deep_sleep_seconds") or _minutes(row, "factor_03"),
            "rem_sleep_seconds": stages.get("rem_sleep_seconds") or _minutes(row, "factor_04"),
            "light_sleep_seconds": stages.get("light_sleep_seconds") or _minutes(row, "factor_02"),
            "awake_seconds": stages.get("awake_seconds") or _minutes(row, "factor_01"),
            "sleep_score": _int(row.get("sleep_score")) or _int(row.get("total_sleep_time_score")),
        }
        existing = by_date.get(sleep_date)
        if existing is None or payload["total_sleep_seconds"] > existing.get("total_sleep_seconds", 0):
            by_date[sleep_date] = payload
    return by_date


def _parse_export_dir(
    base: Path,
    *,
    start_date: date,
    end_date: date,
) -> list[SamsungImportRecord]:
    records: list[SamsungImportRecord] = []
    stage_totals = _aggregate_sleep_stages(base)
    sleep_by_date = _sleep_records_from_stages(base, start_date=start_date, end_date=end_date)
    sleep_by_date.update(
        _sleep_records_from_sleep_csv(
            base,
            stage_totals,
            start_date=start_date,
            end_date=end_date,
        )
    )

    sleep_path = _find_csv(base, "com.samsung.shealth.sleep_combined")
    if sleep_path is not None:
        for row in read_samsung_csv(sleep_path):
            end_time = _parse_timestamp(row.get("end_time", ""), row.get("time_offset"))
            if end_time is None:
                continue
            sleep_date = end_time.date()
            if sleep_date < start_date or sleep_date > end_date:
                continue
            duration_minutes = int(float(row.get("sleep_duration") or 0))
            if duration_minutes <= 0:
                continue
            sleep_id = row.get("datauuid", sleep_date.isoformat())
            stages = stage_totals.get(sleep_id, {})
            sleep_by_date[sleep_date] = {
                "sleep_date": sleep_date.isoformat(),
                "start_time": row.get("start_time"),
                "end_time": row.get("end_time"),
                "total_sleep_seconds": duration_minutes * 60,
                "deep_sleep_seconds": stages.get("deep_sleep_seconds") or _minutes(row, "factor_03"),
                "rem_sleep_seconds": stages.get("rem_sleep_seconds") or _minutes(row, "factor_04"),
                "light_sleep_seconds": stages.get("light_sleep_seconds") or _minutes(row, "factor_02"),
                "awake_seconds": stages.get("awake_seconds") or _minutes(row, "factor_01"),
                "sleep_score": _int(row.get("sleep_score")),
            }

    for sleep_date, payload in sorted(sleep_by_date.items()):
        records.append(
            SamsungImportRecord(
                resource_type=ResourceType.SLEEP,
                provider_record_id=sleep_date.isoformat(),
                payload=payload,
            )
        )

    steps_path = _find_csv(base, "com.samsung.shealth.tracker.pedometer_day_summary")
    if steps_path is not None:
        best_by_day: dict[date, dict[str, Any]] = {}
        for row in read_samsung_csv(steps_path):
            day = _parse_date(row.get("day_time", ""))
            if day is None or day < start_date or day > end_date:
                continue
            step_count = _int(row.get("step_count"))
            if step_count is None:
                continue
            existing = best_by_day.get(day)
            if existing is None or step_count > existing["total_steps"]:
                best_by_day[day] = {
                    "total_steps": step_count,
                    "step_goal": _int(row.get("recommendation")),
                    "distance_meters": _float(row.get("distance")),
                }
        for day, payload in sorted(best_by_day.items()):
            records.append(
                SamsungImportRecord(
                    resource_type=ResourceType.STEPS,
                    provider_record_id=day.isoformat(),
                    payload={"date": day.isoformat(), **payload},
                )
            )

    exercise_path = _find_csv(base, "com.samsung.shealth.exercise")
    if exercise_path is not None:
        prefix = EXERCISE_PREFIX
        for row in read_samsung_csv(exercise_path):
            start = _parse_timestamp(
                row.get(f"{prefix}start_time", ""),
                row.get(f"{prefix}time_offset"),
            )
            if start is None:
                continue
            if start.date() < start_date or start.date() > end_date:
                continue
            duration_ms = _int(row.get(f"{prefix}duration")) or 0
            duration_seconds = max(duration_ms // 1000, 0)
            if duration_seconds <= 0:
                continue
            exercise_type = row.get(f"{prefix}exercise_type", "") or "exercise"
            activity_type = EXERCISE_TYPE_NAMES.get(exercise_type, f"exercise_{exercise_type}")
            distance = _float(row.get(f"{prefix}distance"))
            mean_speed = _float(row.get(f"{prefix}mean_speed"))
            pace = None
            if distance and distance > 0 and duration_seconds > 0:
                pace = duration_seconds / (distance / 1000.0)
            elif mean_speed and mean_speed > 0:
                pace = 1000.0 / mean_speed
            provider_id = row.get(f"{prefix}datauuid") or f"{start.isoformat()}-{duration_seconds}"
            records.append(
                SamsungImportRecord(
                    resource_type=ResourceType.ACTIVITIES,
                    provider_record_id=provider_id,
                    payload={
                        "name": row.get("title") or activity_type.replace("_", " ").title(),
                        "activity_type": activity_type,
                        "start_time": start.isoformat(),
                        "duration_seconds": duration_seconds,
                        "distance_meters": distance,
                        "avg_heart_rate": _int(row.get(f"{prefix}mean_heart_rate")),
                        "max_heart_rate": _int(row.get(f"{prefix}max_heart_rate")),
                        "avg_pace_sec_per_km": pace,
                        "elevation_gain_meters": elevation_gain_from_exercise_row(base, row),
                        "training_load": _float(row.get(f"{prefix}calorie")),
                    },
                )
            )

    stress_path = _find_csv(base, "com.samsung.shealth.stress")
    if stress_path is not None:
        daily_scores: dict[date, list[float]] = defaultdict(list)
        for row in read_samsung_csv(stress_path):
            start = _parse_timestamp(row.get("start_time", ""), row.get("time_offset"))
            score = _float(row.get("score"))
            if start is None or score is None:
                continue
            day = start.date()
            if day < start_date or day > end_date:
                continue
            daily_scores[day].append(score)
        for day, scores in sorted(daily_scores.items()):
            records.append(
                SamsungImportRecord(
                    resource_type=ResourceType.STRESS,
                    provider_record_id=day.isoformat(),
                    payload={
                        "date": day.isoformat(),
                        "recorded_at": datetime.combine(day, datetime.min.time(), tzinfo=UTC).isoformat(),
                        "avg_stress": round(statistics.mean(scores), 1),
                        "max_stress": round(max(scores), 1),
                    },
                )
            )

    hrv_path = _find_csv(base, "com.samsung.health.hrv")
    if hrv_path is not None:
        for row in read_samsung_csv(hrv_path):
            start = _parse_timestamp(row.get("start_time", ""), row.get("time_offset"))
            if start is None:
                continue
            day = start.date()
            if day < start_date or day > end_date:
                continue
            binning = _load_hrv_binning(base, row.get("binning_data", ""))
            rmssd_values = [float(item["rmssd"]) for item in binning if item.get("rmssd")]
            if not rmssd_values:
                continue
            records.append(
                SamsungImportRecord(
                    resource_type=ResourceType.HRV,
                    provider_record_id=row.get("datauuid") or day.isoformat(),
                    payload={
                        "date": day.isoformat(),
                        "recorded_at": start.isoformat(),
                        "hrv_ms": round(statistics.mean(rmssd_values), 2),
                    },
                )
            )

    return records


def _merge_import_records(records: list[SamsungImportRecord]) -> list[SamsungImportRecord]:
    """Dedupe records from multiple export folders; later exports win."""
    merged: dict[tuple[ResourceType, str], SamsungImportRecord] = {}
    for record in records:
        merged[(record.resource_type, record.provider_record_id)] = record
    return list(merged.values())


def parse_export_records(
    export_dir: Path,
    *,
    start_date: date,
    end_date: date,
) -> list[SamsungImportRecord]:
    records: list[SamsungImportRecord] = []
    for base in iter_export_dirs(export_dir):
        records.extend(
            _parse_export_dir(
                base,
                start_date=start_date,
                end_date=end_date,
            )
        )
    return _merge_import_records(records)


def _int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _minutes(row: dict[str, str], key: str) -> int | None:
    value = _int(row.get(key))
    return value * 60 if value is not None else None
