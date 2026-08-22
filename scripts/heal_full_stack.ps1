# Full stack recovery: Docker, VPN/network, media stack, coach stack, music ingest, Caddy.
param(
    [switch]$SkipVpn,
    [switch]$SkipMusic,
    [switch]$SkipCoach,
    [switch]$SkipMedia
)

$ErrorActionPreference = "Stop"

$CoachRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $CoachRoot "logs"
$LogFile = Join-Path $LogDir "heal-full-stack.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Host $Message
}

function Invoke-Step([string]$Label, [scriptblock]$Action) {
    Write-Log "==> $Label"
    try {
        & $Action
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            Write-Log "WARNING: $Label exited with code $LASTEXITCODE"
        }
    } catch {
        Write-Log "ERROR in ${Label}: $($_.Exception.Message)"
    }
}

Write-Log "Full stack heal started"

$ensureDocker = "C:\ProgramData\docker\media-stack\scripts\ensure-docker-daemon.ps1"
$bootMedia = "C:\ProgramData\docker\media-stack\scripts\boot-start-media-stack.ps1"
$vpnWatchdog = Join-Path $CoachRoot "scripts\vpn_network_watchdog.ps1"
$coachStart = Join-Path $CoachRoot "scripts\start_coach_docker.ps1"
$fixMusic = Join-Path $CoachRoot "scripts\music-ingest\fix_music_ingest.ps1"
$reloadCaddy = Join-Path $CoachRoot "scripts\reload_caddy.ps1"
$linkProwlarr = "C:\ProgramData\mediapc-stack\link-prowlarr-apps.ps1"
$watchdog = Join-Path $CoachRoot "scripts\watchdog_services.ps1"

Invoke-Step "Ensure Docker daemon" {
    if (Test-Path $ensureDocker) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ensureDocker
    }
}

if (-not $SkipVpn -and (Test-Path $vpnWatchdog)) {
    Invoke-Step "VPN / network recovery" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $vpnWatchdog -ForceRecovery
    }
}

if (-not $SkipMedia -and (Test-Path $bootMedia)) {
    Invoke-Step "Docker media stack" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootMedia
    }
}

if (-not $SkipCoach -and (Test-Path $coachStart)) {
    Invoke-Step "Endurance coach stack" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $coachStart
    }
}

if (-not $SkipMusic -and (Test-Path $fixMusic)) {
    Invoke-Step "Music ingest pipeline" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $fixMusic
    }
}

if (Test-Path $reloadCaddy) {
    Invoke-Step "Reload Caddy" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $reloadCaddy
    }
}

if (Test-Path $linkProwlarr) {
    Invoke-Step "Link Prowlarr apps" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $linkProwlarr
    }
}

if (Test-Path $watchdog) {
    Invoke-Step "Service watchdog pass" {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $watchdog
    }
}

Write-Log "Full stack heal complete. Log: $LogFile"
