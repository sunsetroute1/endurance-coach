# Recover Docker media stack (*arr, slskd, Navidrome) and Prowlarr links.
$ErrorActionPreference = "Stop"

$CoachRoot = Split-Path -Parent $PSScriptRoot
$bootMedia = "C:\ProgramData\docker\media-stack\scripts\boot-start-media-stack.ps1"
$ensureDocker = "C:\ProgramData\docker\media-stack\scripts\ensure-docker-daemon.ps1"
$vpnWatchdog = Join-Path $CoachRoot "scripts\vpn_network_watchdog.ps1"
$linkProwlarr = "C:\ProgramData\mediapc-stack\link-prowlarr-apps.ps1"

if (Test-Path $ensureDocker) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ensureDocker
}
if (Test-Path $vpnWatchdog) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $vpnWatchdog -ForceRecovery
}
if (Test-Path $bootMedia) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootMedia
}
if (Test-Path $linkProwlarr) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $linkProwlarr
}
