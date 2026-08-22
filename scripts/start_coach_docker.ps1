# Start/recover endurance-coach Docker stack (idempotent).
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'coach-stack-helpers.ps1')

if (-not (Test-CoachDockerMode)) {
    Write-Host 'Coach Docker mode is not active (missing coach-active.marker)'
    exit 1
}

$ok = Invoke-CoachDockerRecovery -Reason 'manual' -StartupWaitSec 40
if (-not $ok) { exit 1 }

docker compose -f $script:CoachComposeFile ps
Write-Host 'Coach Docker stack is up' -ForegroundColor Green
