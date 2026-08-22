# One-shot recovery pass after boot/auto-login. Catches Docker Desktop still starting after power loss.
$ErrorActionPreference = 'Continue'

$LogDir = 'C:\ProgramData\mediapc-stack\logs'
$LogFile = Join-Path $LogDir 'post-boot-recovery.log'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-RecoveryLog {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [$Level] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

Write-RecoveryLog 'Post-boot stack recovery started'

$bootScript = 'C:\ProgramData\docker\media-stack\scripts\boot-start-media-stack.ps1'
$dockerHelpers = 'C:\ProgramData\docker\media-stack\scripts\docker-stack-helpers.ps1'

if (Test-Path $dockerHelpers) {
    . $dockerHelpers
    $deadline = (Get-Date).AddMinutes(5)
    $dockerReady = $false
    while ((Get-Date) -lt $deadline) {
        if (Get-Command Ensure-DockerDaemon -ErrorAction SilentlyContinue) {
            if (Ensure-DockerDaemon -Quiet) {
                $dockerReady = $true
                break
            }
        } elseif (Get-Command docker -ErrorAction SilentlyContinue) {
            docker info 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $dockerReady = $true
                break
            }
        }
        Start-Sleep -Seconds 15
    }
    if ($dockerReady) {
        Write-RecoveryLog 'Docker daemon is ready'
    } else {
        Write-RecoveryLog 'Docker daemon not ready after 5 minutes; continuing with boot script anyway' 'WARN'
    }
}

if (Test-Path $bootScript) {
    Write-RecoveryLog "Running $bootScript"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $bootScript 2>&1 |
        ForEach-Object { Write-RecoveryLog $_ }
    if ($LASTEXITCODE -ne 0) {
        Write-RecoveryLog "Boot script exited with code $LASTEXITCODE" 'WARN'
    }
} else {
    Write-RecoveryLog "Missing boot script: $bootScript" 'ERR'
    exit 1
}

Write-RecoveryLog 'Post-boot stack recovery complete'
exit 0
