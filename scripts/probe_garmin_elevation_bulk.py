"""Probe multiple 2021-2022 Garmin activities for elevation in API, FIT, and TCX."""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

from garminconnect import Garmin

ActivityDownloadFormat = Garmin.ActivityDownloadFormat


def main() -> None:
    if len(sys.argv) > 1:
        lines = Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines()
    else:
        lines = sys.stdin.read().splitlines()

    rows: list[list[str]] = []
    for line in lines:
        line = line.strip()
        if line:
            rows.append(line.split("|"))

    token_dir = Path.home() / ".garminconnect"
    client = Garmin()
    client.login(str(token_dir))

    api_elev = fit_elev = tcx_elev = 0
    fit_stubs = 0

    for aid, yr, mi in rows:
        act = client.get_activity(aid)
        dto = act.get("summaryDTO", {})
        eg = dto.get("elevationGain")
        if eg:
            api_elev += 1
            print(f"API ELEV {yr} id={aid} mi={mi} gain={eg}")

        try:
            raw = client.download_activity(aid, ActivityDownloadFormat.ORIGINAL)
            if raw[:2] == b"PK":
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    fit_data = zf.read(zf.namelist()[0])
            else:
                fit_data = raw

            from fitparse import FitFile

            alts: list[float] = []
            for rec in FitFile(io.BytesIO(fit_data)).get_messages("record"):
                fields = {f.name: f.value for f in rec.fields}
                alt = fields.get("altitude")
                if alt is None:
                    alt = fields.get("enhanced_altitude")
                if alt is not None:
                    alts.append(float(alt))
            if alts:
                fit_elev += 1
                gain = sum(max(0, alts[i + 1] - alts[i]) for i in range(len(alts) - 1))
                print(
                    f"FIT ELEV {yr} id={aid} mi={mi} points={len(alts)} "
                    f"gain~{gain:.0f}m size={len(fit_data)}"
                )
            elif len(fit_data) < 5000:
                fit_stubs += 1
                print(f"FIT stub {yr} id={aid} mi={mi} size={len(fit_data)} no_alt")
        except Exception as exc:
            print(f"FIT fail {aid}: {exc}")

        try:
            tcx = client.download_activity(aid, ActivityDownloadFormat.TCX).decode(
                "utf-8", errors="ignore"
            )
            if "<AltitudeMeters>" in tcx:
                tcx_elev += 1
                alts = [float(x) for x in re.findall(r"<AltitudeMeters>([\d.]+)</AltitudeMeters>", tcx)]
                gain = sum(max(0, alts[i + 1] - alts[i]) for i in range(len(alts) - 1)) if alts else 0
                print(f"TCX ELEV {yr} id={aid} mi={mi} points={len(alts)} gain~{gain:.0f}m")
        except Exception as exc:
            print(f"TCX fail {aid}: {exc}")

    print(
        f"\nSUMMARY checked={len(rows)} api_elev={api_elev} "
        f"fit_elev={fit_elev} fit_stubs={fit_stubs} tcx_elev={tcx_elev}"
    )


if __name__ == "__main__":
    main()
