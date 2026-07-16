# Backfill Garmin activity lap splits with safe rate limiting.
# Usage:
#   powershell -File backfill_activities.ps1
#   powershell -File backfill_activities.ps1 -Limit 50
#   powershell -File backfill_activities.ps1 -Delay 2.5 -Full
param(
    [int]$Limit = 0,
    [double]$Delay = 1.5,
    [int]$BatchSize = 10,
    [switch]$Full,
    [switch]$DryRun,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "backfill-activities.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Set-Location $ProjectRoot

$argsList = @("-m", "endurance_coach.scripts.backfill_activities", "--delay", $Delay, "--batch-size", $BatchSize)
if ($Limit -gt 0) { $argsList += @("--limit", $Limit) }
if ($Full.IsPresent) { $argsList += "--full" }
if ($DryRun.IsPresent) { $argsList += "--dry-run" }
if ($Verbose.IsPresent) { $argsList += "--verbose" }

"$(Get-Date -Format o) Starting activity backfill delay=$Delay limit=$Limit full=$($Full.IsPresent)" |
    Out-File -FilePath $LogFile -Append -Encoding utf8

$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python @argsList 2>&1 | Tee-Object -FilePath $LogFile -Append
$exitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorAction
if ($exitCode -ne 0) { exit $exitCode }

"$(Get-Date -Format o) Backfill complete." | Out-File -FilePath $LogFile -Append -Encoding utf8
