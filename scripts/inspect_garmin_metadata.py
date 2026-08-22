"""Inspect Garmin metadata for longest 2021-2022 activities."""

from __future__ import annotations

import subprocess
from pathlib import Path

from garminconnect import Garmin


def main() -> None:
    sql = """
    SELECT a.provider_record_id,
           ROUND((a.distance_meters/1609.34)::numeric, 1),
           a.started_at::date
    FROM activities a
    WHERE a.provider='garmin'
      AND EXTRACT(YEAR FROM a.started_at) IN (2021, 2022)
    ORDER BY a.distance_meters DESC
    LIMIT 10
    """
    out = subprocess.check_output(
        [
            "docker",
            "exec",
            "endurance-postgres",
            "psql",
            "-U",
            "endurance",
            "-d",
            "endurance_coach",
            "-t",
            "-A",
            "-c",
            sql,
        ],
        text=True,
    )

    client = Garmin()
    client.login(str(Path.home() / ".garminconnect"))

    for line in out.splitlines():
        if not line.strip():
            continue
        aid, mi, dt = line.split("|")
        act = client.get_activity(aid)
        meta = act.get("metadataDTO", {}) or {}
        dto = act.get("summaryDTO", {}) or {}
        dev = meta.get("deviceMetaDataDTO") or {}
        print(
            f"{dt} id={aid} mi={mi} elev={dto.get('elevationGain')} "
            f"manual={meta.get('isManual')} corrected={meta.get('elevationCorrected')} "
            f"device={dev.get('deviceTypePk')}/{dev.get('displayName')} "
            f"parent={meta.get('parentId')}"
        )


if __name__ == "__main__":
    main()
