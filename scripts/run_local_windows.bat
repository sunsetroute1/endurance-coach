# Run endurance-coach locally WITHOUT Docker (Windows)
# Requires: Python 3.12+, PostgreSQL installed natively

@echo off
setlocal
cd /d "%~dp0.."

echo === Endurance Coach - Native Windows Setup ===
echo.

where psql >nul 2>&1
if errorlevel 1 (
    echo PostgreSQL not found. Install with:
    echo   winget install PostgreSQL.PostgreSQL.16
    echo.
    echo Or download from https://www.postgresql.org/download/windows/
    echo Use password: endurance, port 5432, then create database endurance_coach
    exit /b 1
)

echo [1/4] Installing Python package...
python -m pip install -e ".[dev]" -q

echo [2/4] Running database migrations...
python -m alembic upgrade head
if errorlevel 1 (
    echo Migration failed. Ensure PostgreSQL is running and DATABASE_URL in .env is correct.
    exit /b 1
)

echo [3/4] Starting API on http://localhost:8000 ...
echo Press Ctrl+C to stop.
python -m uvicorn endurance_coach.api.main:app --host 0.0.0.0 --port 8000 --reload
