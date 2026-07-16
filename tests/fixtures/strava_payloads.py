"""Sample Strava API payloads for tests."""

STRAVA_ACTIVITY_SUMMARY = {
    "id": 123456789,
    "name": "Morning Run",
    "type": "Run",
    "sport_type": "Run",
    "start_date": "2026-07-14T14:00:00Z",
    "start_date_local": "2026-07-14T08:00:00Z",
    "elapsed_time": 3720,
    "moving_time": 3600,
    "distance": 10000.0,
    "average_heartrate": 145,
    "max_heartrate": 168,
    "total_elevation_gain": 120.0,
    "suffer_score": 82,
}

STRAVA_ACTIVITY_DETAIL = {
    **STRAVA_ACTIVITY_SUMMARY,
    "description": "Easy aerobic run",
    "calories": 620.0,
}

STRAVA_ACTIVITY_PAYLOAD = {
    "summary": STRAVA_ACTIVITY_SUMMARY,
    "detail": STRAVA_ACTIVITY_DETAIL,
}
