# Roll back music ingestion automation to pre-pipeline state.
$ErrorActionPreference = "Continue"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$LogDir = Join-Path $RepoRoot "logs"
$PidFile = Join-Path $LogDir "music-ingest.pid"

Write-Host "Stopping music ingest watcher..."
if (Test-Path $PidFile) {
    $pidValue = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($pidValue) {
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*music-ingest*src\watcher.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

foreach ($task in @("MusicIngestWatcher", "MusicIngestFallbackScan")) {
    $existing = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $task -Confirm:$false
        Write-Host "Removed scheduled task $task"
    }
}

Write-Host ""
Write-Host "Rollback complete for automation tasks and watcher process."
Write-Host "Manual restore if needed:"
Write-Host "  - slskd downloads: E:\Music"
Write-Host "  - Navidrome MusicFolder: E:\Music"
Write-Host "  - Remove services\music-ingest\.venv"
Write-Host "  - Remove %APPDATA%\beets\config.yaml (optional)"
