# Samsung Health Data SDK

Endurance Coach stores Samsung Health data in the same PostgreSQL tables as Garmin (`sleep_records`, `steps_records`, `activities`, `hrv_records`), tagged with `provider = samsung_health`.

## Important constraint

The **Samsung Health Data SDK runs only on Android** (physical device, Samsung Health 6.30.2+). It cannot run on your Windows server. The architecture is:

```
Android phone (Samsung Health Data SDK)
    → POST /api/v1/sync/samsung/import
    → raw_payloads
    → POST /api/v1/process
    → normalized PostgreSQL tables
```

## Server setup

1. Ensure `API_SECRET_KEY` is set in `.env`.
2. Optional: set import directory (defaults to `~/.endurance-coach/samsung_health_import`):

```env
SAMSUNG_HEALTH_IMPORT_DIR=~/.endurance-coach/samsung_health_import
SAMSUNG_HEALTH_SYNC_DAYS=365
```

3. Restart the API after config changes.

### API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1/providers/samsung/status` | Connection/import status |
| POST | `/api/v1/sync/samsung/import` | Upload batch from Android app |
| POST | `/api/v1/sync/samsung` | Import pending JSON files from import dir |
| POST | `/api/v1/process` | Normalize raw payloads into PostgreSQL |

All endpoints require `Authorization: Bearer YOUR_API_SECRET_KEY`.

### Import payload format

```json
{
  "schema_version": 1,
  "device_id": "my-galaxy-s24",
  "records": [
    {
      "resource_type": "sleep",
      "provider_record_id": "2026-07-16",
      "payload": {
        "sleep_date": "2026-07-16",
        "total_sleep_seconds": 27900,
        "deep_sleep_seconds": 5400,
        "rem_sleep_seconds": 3600,
        "light_sleep_seconds": 17100,
        "awake_seconds": 900,
        "sleep_score": 84
      }
    },
    {
      "resource_type": "steps",
      "provider_record_id": "2026-07-16",
      "payload": {
        "date": "2026-07-16",
        "total_steps": 9124,
        "step_goal": 10000,
        "distance_meters": 7012.5
      }
    },
    {
      "resource_type": "activities",
      "provider_record_id": "exercise-uuid",
      "payload": {
        "name": "Morning Run",
        "activity_type": "running",
        "start_time": "2026-07-14T07:30:00-06:00",
        "duration_seconds": 3720,
        "distance_meters": 10250,
        "avg_heart_rate": 142,
        "max_heart_rate": 168,
        "elevation_gain_meters": 210
      }
    }
  ]
}
```

Supported `resource_type` values: `sleep`, `steps`, `activities`, `hrv`.

### Manual file import (no phone app yet)

1. Save a batch JSON file to `SAMSUNG_HEALTH_IMPORT_DIR`.
2. Run:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/sync/samsung `
  -H "Authorization: Bearer $env:API_SECRET_KEY"
curl.exe -X POST http://127.0.0.1:8000/api/v1/process `
  -H "Authorization: Bearer $env:API_SECRET_KEY"
```

Processed files move to `samsung_health_import/processed/`.

## Android companion app

See `android/samsung-health-sync/README.md`.

Summary:

1. Download **Samsung Health Data SDK** (`samsung-health-data-api.aar`) from [Samsung Developer](https://developer.samsung.com/health/data).
2. Enable **Developer mode** in Samsung Health (read-only access; no partner request needed for development).
3. Open `android/samsung-health-sync` in Android Studio.
4. Place the `.aar` in `android/samsung-health-sync/app/libs/`.
5. Configure your server URL and API key in the app settings.
6. Run **Sync historical data** on your phone.

## Overlap with Garmin data

Analytics queries currently read all providers for a user. If both Garmin and Samsung supply sleep/steps, both appear in rollups. Prefer one source for wellness metrics, or extend analytics with a provider preference later.

## Historical backfill

The Android app reads Samsung Health history using `ReadDataRequest` time filters (default: 365 days). After the first upload, run `/process` and `/analytics/compute` on the server.
