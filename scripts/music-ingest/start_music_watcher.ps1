# Start the music ingestion watchdog (Python + watchdog).
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$IngestRoot = Join-Path $RepoRoot "services\music-ingest"
$VenvPython = Join-Path $IngestRoot ".venv\Scripts\python.exe"
$WatcherScript = Join-Path $IngestRoot "src\watcher.py"
$EnvFile = Join-Path $IngestRoot "config\pipeline.env"
$LogDir = Join-Path $RepoRoot "logs"
$PidFile = Join-Path $LogDir "music-ingest.pid"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path $VenvPython)) {
    throw "Music ingest venv missing. Run install_music_ingest.ps1 first."
}

if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Host "Music ingest watcher already running (PID $oldPid)"
        exit 0
    }
}

$args = @(
    $WatcherScript,
    "--env-file", $EnvFile,
    "--venv-python", $VenvPython
)

$stdoutLog = Join-Path $LogDir "music-ingest.stdout.log"
$stderrLog = Join-Path $LogDir "music-ingest.stderr.log"

$proc = Start-Process `
    -FilePath $VenvPython `
    -ArgumentList $args `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

$proc.Id | Out-File -FilePath $PidFile -Encoding ascii -NoNewline
Write-Host "Started music ingest watcher (PID $($proc.Id))"
