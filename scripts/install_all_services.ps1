# Restore all endurance-coach hidden scheduled tasks in-process (no nested PowerShell).
$ErrorActionPreference = "Stop"

$coachHelpers = Join-Path $PSScriptRoot "coach-stack-helpers.ps1"
$coachDocker = $false
if (Test-Path $coachHelpers) {
    . $coachHelpers
    $coachDocker = Test-CoachDockerMode
}

$installers = @(
    "install_garmin_sync_schedule.ps1",
    "install_watchdog_schedule.ps1",
    "install_vpn_network_watchdog.ps1"
)
if (-not $coachDocker) {
    $installers = @(
        "install_windows_startup.ps1",
        "install_mcp_startup.ps1"
    ) + $installers + @("install_slskd_startup.ps1")
} else {
    Write-Host "Coach Docker mode active; skipping native API/MCP/Slskd task installers."
    foreach ($nativeTask in @('EnduranceCoachAPI', 'EnduranceCoachMCP', 'Slskd')) {
        $existing = Get-ScheduledTask -TaskName $nativeTask -ErrorAction SilentlyContinue
        if ($existing -and $existing.State -ne 'Disabled') {
            Disable-ScheduledTask -TaskName $nativeTask -ErrorAction SilentlyContinue | Out-Null
            Write-Host "Disabled redundant native task: $nativeTask"
        }
    }
}

foreach ($name in $installers) {
    $path = Join-Path $PSScriptRoot $name
    if (-not (Test-Path $path)) {
        throw "Missing installer: $path"
    }
    Write-Host "Running $name..."
    & $path
}

$musicWatcherInstaller = Join-Path $PSScriptRoot "music-ingest\install_music_watcher_startup.ps1"
$musicFallbackInstaller = Join-Path $PSScriptRoot "music-ingest\install_music_ingest_fallback.ps1"
if (Test-Path $musicWatcherInstaller) {
    Write-Host "Running install_music_watcher_startup.ps1..."
    & $musicWatcherInstaller
}
if (Test-Path $musicFallbackInstaller) {
    Write-Host "Running install_music_ingest_fallback.ps1..."
    & $musicFallbackInstaller
}

$mediaStackBootInstaller = 'C:\ProgramData\docker\media-stack\scripts\install_media_stack_boot.ps1'
if (Test-Path $mediaStackBootInstaller) {
    Write-Host "Running install_media_stack_boot.ps1..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $mediaStackBootInstaller
} else {
    Write-Warning "Media stack boot installer not found: $mediaStackBootInstaller"
}

Write-Host ""
Write-Host "All endurance-coach scheduled tasks installed (hidden)."
