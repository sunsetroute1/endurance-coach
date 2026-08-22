# Upgrade Docker Desktop to a pinned release, then recover stacks.
param(
    [string]$Version = "4.86.0",
    [switch]$SkipStackRecovery
)

$ErrorActionPreference = "Stop"

$CoachRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $CoachRoot "logs"
$LogFile = Join-Path $LogDir "update-docker-desktop.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Host $Message
}

function Get-DockerDesktopVersion {
    try {
        $version = docker version --format "{{.Server.Version}}" 2>$null
        if (-not $version) { return $null }
        $info = docker version 2>$null | Out-String
        if ($info -match "Docker Desktop (\d+\.\d+\.\d+)") {
            return $Matches[1]
        }
    } catch {}
    return $null
}

Write-Log "Docker Desktop update started (target=$Version)"
$current = Get-DockerDesktopVersion
Write-Log "Current Docker Desktop version: $current"

if ($current -eq $Version) {
    Write-Log "Already on Docker Desktop $Version"
} else {
    Write-Log "Installing Docker Desktop $Version via winget..."
    winget upgrade --id Docker.DockerDesktop `
        --version $Version `
        --accept-package-agreements `
        --accept-source-agreements `
        --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        Write-Log "winget upgrade failed with exit code $LASTEXITCODE"
        exit $LASTEXITCODE
    }

    Write-Log "Restarting Docker Desktop..."
    $restartScript = Join-Path $CoachRoot "scripts\restart_docker_desktop.ps1"
    if (Test-Path $restartScript) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $restartScript
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Docker restart script failed"
            exit $LASTEXITCODE
        }
    } else {
        Start-Sleep -Seconds 20
        $deadline = (Get-Date).AddMinutes(3)
        while ((Get-Date) -lt $deadline) {
            docker info 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { break }
            Start-Sleep -Seconds 10
        }
    }

    $updated = Get-DockerDesktopVersion
    Write-Log "Docker Desktop version after update: $updated"
    if ($updated -ne $Version) {
        Write-Log "WARNING: expected $Version but detected $updated"
    }
}

if ($SkipStackRecovery) {
    Write-Log "Skipping stack recovery"
    exit 0
}

Write-Log "Recovering full stack..."
$healScript = Join-Path $CoachRoot "scripts\heal_full_stack.ps1"
if (Test-Path $healScript) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $healScript
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Full stack heal exited with code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
} else {
    Write-Log "heal_full_stack.ps1 not found"
    exit 1
}

Write-Log "Docker update and stack recovery complete"
exit 0
