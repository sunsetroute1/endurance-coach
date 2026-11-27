# Delegate to the watchboard updater. That script never downgrades, and it
# only installs at 4:00 AM (or with -InstallNow) so a live Docker session
# is not interrupted.
param(
    [string]$Version = '',
    [switch]$SkipStackRecovery,
    [switch]$InstallNow,
    [int]$ScheduleHour = 4
)

$ErrorActionPreference = 'Stop'
$WatchScript = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'automation-watchboard\scripts\update-docker-desktop.ps1'
if (-not (Test-Path -LiteralPath $WatchScript)) {
    throw "Watchboard Docker updater not found: $WatchScript"
}

$forward = @()
if ($Version) { $forward += @('-Version', $Version) }
if ($SkipStackRecovery) { $forward += '-SkipStackRecovery' }
if ($InstallNow) { $forward += '-InstallNow' }
$forward += @('-ScheduleHour', [string]$ScheduleHour)
& $WatchScript @forward
exit $LASTEXITCODE
