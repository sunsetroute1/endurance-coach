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
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$RescanScript = Join-Path $PSScriptRoot "rescan_navidrome.ps1"
$DockerMarker = "C:\ProgramData\docker\media-stack\music-active.marker"
if ((Test-Path $RescanScript) -and (Test-Path $DockerMarker)) {
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:4533/ping" -TimeoutSec 3
        Write-Host "Triggering Navidrome incremental rescan after beets import..."
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $RescanScript -Incremental
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Navidrome incremental rescan failed with exit code $LASTEXITCODE"
        }
    } catch {
        Write-Warning "Navidrome not reachable; skipped post-import rescan"
    }
}

exit 0
