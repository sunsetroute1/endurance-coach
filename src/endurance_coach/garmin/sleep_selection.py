"""Canonical sleep selection shared by readiness and get_sleep_summary."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID


async def sleep_record_for_local_date(
    data_repo: Any,
    user_id: UUID,
    target_date: date,
) -> Any | None:
    """Return the sleep row whose calendar date is the athlete-local target date.

    Selection is ``SleepRecord.sleep_date == target_date``. There is no
    fetch-time ceiling and no prior-night fallback. A UTC midnight timestamp
    is not a calendar date and is not consulted.
    """
    return await data_repo.get_sleep_for_date(user_id, target_date)
