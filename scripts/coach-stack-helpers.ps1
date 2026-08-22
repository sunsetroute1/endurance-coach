# Shared helpers for Docker endurance-coach stack (Stage 6+)
$ErrorActionPreference = 'Continue'

$script:CoachProjectRoot = Split-Path -Parent $PSScriptRoot
$script:CoachMarker = Join-Path $script:CoachProjectRoot 'coach-active.marker'
$script:CoachComposeFile = Join-Path $script:CoachProjectRoot 'docker-compose.yml'
$script:CoachRecoveryLog = Join-Path $script:CoachProjectRoot 'logs\coach-docker.log'

function Write-CoachLog {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [$Level] $Message"
    $dir = Split-Path $script:CoachRecoveryLog -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Add-Content -Path $script:CoachRecoveryLog -Value $line -Encoding UTF8
}

function Test-CoachDockerMode {
    return Test-Path $script:CoachMarker
}

function Test-CoachPort {
    param([int]$Port, [string]$HealthUrl, [int]$TimeoutSec = 10)

    $listening = [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if (-not $listening) { return $false }
    if (-not $HealthUrl) { return $true }
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch {
        return $false
    }
}

function Get-CoachPortChecks {
    return @(
        @{ Port = 5432; Url = $null }
        @{ Port = 8000; Url = 'http://127.0.0.1:8000/health' }
        @{ Port = 8080; Url = 'http://127.0.0.1:8080/health' }
    )
}

function Ensure-CoachDockerDaemon {
    param([int]$TimeoutSec = 120)

    $helpers = 'C:\ProgramData\docker\media-stack\scripts\docker-stack-helpers.ps1'
    if (Test-Path $helpers) {
        . $helpers
        return Ensure-DockerDaemon -TimeoutSec $TimeoutSec
    }

    try {
        & docker info 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-CoachComposeEnvArgs {
    $sync = 'C:\ProgramData\mediapc-stack\scripts\sync-resource-limits.ps1'
    if (Test-Path $sync) {
        try {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $sync | Out-Null
        } catch {
            Write-CoachLog "Resource limit sync failed: $_" 'WARN'
        }
    }

    $args = @()
    $limits = Join-Path $script:CoachProjectRoot 'resource-limits.env'
    if (Test-Path $limits) {
        $args += '--env-file', $limits
    }
    return $args
}

function Repair-CoachContainerNames {
    $expected = @('endurance-postgres', 'endurance-api', 'endurance-mcp')
    foreach ($expectedName in $expected) {
        $aliases = @(docker ps -a --format '{{.Names}}' 2>$null |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and $_ -ne $expectedName -and ($_ -eq $expectedName -or $_.EndsWith("_$expectedName")) })
        foreach ($alias in $aliases) {
            Write-CoachLog "Removing misnamed coach container: $alias (expected $expectedName)" 'WARN'
            docker rm -f $alias 2>$null | Out-Null
        }
    }
}

function Start-CoachDockerStack {
    param([switch]$ForceRecreate)

    if (-not (Test-Path $script:CoachComposeFile)) {
        throw "Compose file not found: $script:CoachComposeFile"
    }

    Repair-CoachContainerNames

    Push-Location $script:CoachProjectRoot
    try {
        $args = @('compose') + (Get-CoachComposeEnvArgs) + @('up', '-d', '--remove-orphans')
        if ($ForceRecreate) {
            $args += '--force-recreate'
        }
        & docker @args 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose up failed (exit $LASTEXITCODE)"
        }
    } finally {
        Pop-Location
    }
}

function Invoke-CoachDockerRecovery {
    param(
        [string]$Reason = 'recovery',
        [int]$StartupWaitSec = 35
    )

    if (-not (Test-CoachDockerMode)) {
        Write-CoachLog "Coach Docker recovery skipped ($Reason); marker missing" 'WARN'
        return $false
    }

    Write-CoachLog "Coach Docker recovery ($Reason)"
    if (-not (Ensure-CoachDockerDaemon)) {
        return $false
    }

    Start-CoachDockerStack
    Start-Sleep -Seconds $StartupWaitSec

    $failed = @()
    foreach ($check in (Get-CoachPortChecks)) {
        if (-not (Test-CoachPort -Port $check.Port -HealthUrl $check.Url)) {
            $failed += $check.Port
        }
    }

    if ($failed.Count -gt 0) {
        Write-CoachLog "Coach ports still down: $($failed -join ', ')" 'ERR'
        return $false
    }

    Write-CoachLog "Coach Docker recovery complete ($Reason)"
    return $true
}
