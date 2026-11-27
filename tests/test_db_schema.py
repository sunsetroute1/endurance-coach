"""Tests for database model metadata."""

from endurance_coach.db import models  # noqa: F401
from endurance_coach.db.base import Base


def test_all_tables_registered() -> None:
    table_names = set(Base.metadata.tables.keys())
    expected = {
        "users",
        "provider_connections",
        "sync_jobs",
        "raw_payloads",
        "activities",
        "sleep_records",
        "hrv_records",
        "body_battery_records",
        "training_readiness_records",
        "stress_records",
        "steps_records",
        "running_dynamics_records",
        "computed_metrics",
    }
    assert expected.issubset(table_names)


def test_normalized_rows_cannot_delete_raw_payloads() -> None:
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            if foreign_key.column.table.name != "raw_payloads":
                continue
            assert foreign_key.ondelete == "RESTRICT"


def test_raw_payloads_has_dedup_constraint() -> None:
    table = Base.metadata.tables["raw_payloads"]
    constraint_names = {c.name for c in table.constraints if c.name}
    assert "uq_raw_payload_user_hash" in constraint_names
