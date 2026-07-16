# Run a one-shot beets scan/import (used by fallback scheduled task and manual testing).
param(
    [switch]$ScanOnce
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$IngestRoot = Join-Path $RepoRoot "services\music-ingest"
$VenvPython = Join-Path $IngestRoot ".venv\Scripts\python.exe"
$WatcherScript = Join-Path $IngestRoot "src\watcher.py"
$EnvFile = Join-Path $IngestRoot "config\pipeline.env"

if (-not (Test-Path $VenvPython)) {
    throw "Music ingest venv missing. Run install_music_ingest.ps1 first."
}

$args = @(
    $WatcherScript,
    "--env-file", $EnvFile,
    "--venv-python", $VenvPython,
    "--scan-once"
)

& $VenvPython @args
