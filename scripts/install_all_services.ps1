# Restore all endurance-coach hidden scheduled tasks in-process (no nested PowerShell).
$ErrorActionPreference = "Stop"

$installers = @(
    "install_windows_startup.ps1",
    "install_mcp_startup.ps1",
    "install_garmin_sync_schedule.ps1",
    "install_watchdog_schedule.ps1",
    "install_slskd_startup.ps1"
)

foreach ($name in $installers) {
    $path = Join-Path $PSScriptRoot $name
    if (-not (Test-Path $path)) {
        throw "Missing installer: $path"
    }
    Write-Host "Running $name..."
    & $path
}

Write-Host ""
Write-Host "All endurance-coach scheduled tasks installed (hidden)."
