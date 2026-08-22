# Sync Garmin data and run process + analytics pipeline.
# Usage:
#   powershell -File sync_garmin_pipeline.ps1
#   powershell -File sync_garmin_pipeline.ps1 -FullSync
#   powershell -File sync_garmin_pipeline.ps1 -WaitForMorningReadiness
param(
    [switch]$FullSync,
    [switch]$WaitForMorningReadiness,
    [string]$ApiBase = "http://localhost:8000",
    [string]$Since,
    [int]$MorningPollMinutes = 1,
    [int]$MorningPollMaxAttempts = 2
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "sync-pipeline.log"
$StatusFile = Join-Path $LogDir "morning-readiness-status.json"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
}

function Test-InMorningSyncWindow {
    # After manual Garmin Connect sync (~7-9 AM), poll only until the 9:01 AM cutoff.
    $now = Get-Date
    return ($now.Hour -eq 9 -and $now.Minute -le 1)
}

function Invoke-ApiPost([string]$Path, [hashtable]$Body) {
    $json = $Body | ConvertTo-Json -Compress
    $headers = @{}
    if ($script:ApiSecretKey) {
        $headers["Authorization"] = "Bearer $script:ApiSecretKey"
    }
    return Invoke-RestMethod -Method POST -Uri "$ApiBase$Path" -ContentType "application/json" -Headers $headers -Body $json
}

function Invoke-ApiGet([string]$Path) {
    $headers = @{}
    if ($script:ApiSecretKey) {
        $headers["Authorization"] = "Bearer $script:ApiSecretKey"
    }
    return Invoke-RestMethod -Method GET -Uri "$ApiBase$Path" -Headers $headers
}

function Save-MorningReadinessStatus($Status) {
    $Status | ConvertTo-Json -Depth 6 | Out-File -FilePath $StatusFile -Encoding utf8
}

function Invoke-SyncPipelineCore() {
    $syncBody = @{}
    if ($FullSync) { $syncBody.full_sync = $true }
    if ($Since) { $syncBody.since = $Since }

    Write-Log "Starting Garmin sync (full_sync=$($FullSync.IsPresent), since=$Since)..."
    $sync = Invoke-ApiPost "/api/v1/sync/garmin" $syncBody
    Write-Log ("Sync status: {0} synced={1}" -f $sync.status, ($sync.resources_synced | ConvertTo-Json -Compress))

    Write-Log "Processing normalized records..."
    $processLimit = if ($FullSync) { 500 } else { 100 }
    $process = Invoke-ApiPost "/api/v1/process" @{ limit = $processLimit }
    Write-Log ("Processed: {0}" -f ($process.processed | ConvertTo-Json -Compress))

    Write-Log "Computing analytics..."
    $analytics = Invoke-ApiPost "/api/v1/analytics/compute" @{}
    Write-Log ("Analytics families: {0}" -f ($analytics.families -join ", "))
}

function Get-MorningReadinessStatus() {
    return Invoke-ApiGet "/api/v1/garmin/morning-readiness-status"
}

$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*API_SECRET_KEY=(.+)$') {
            $script:ApiSecretKey = $Matches[1].Trim()
            break
        }
    }
}

try {
    Invoke-SyncPipelineCore

    $status = Get-MorningReadinessStatus
    Save-MorningReadinessStatus $status
    Write-Log ("Morning readiness: status={0} missing={1} last_successful_metric_timestamp={2}" -f `
        $status.status, ($status.missing_fields -join ","), $status.last_successful_metric_timestamp)

    $shouldWait = $WaitForMorningReadiness.IsPresent -or (Test-InMorningSyncWindow)
    if ($shouldWait -and $status.status -eq "partial") {
        Write-Log ("Morning readiness incomplete; polling every {0} min up to {1} attempts (9:01 AM cutoff)" -f `
            $MorningPollMinutes, $MorningPollMaxAttempts)
        for ($attempt = 1; $attempt -le $MorningPollMaxAttempts; $attempt++) {
            if (-not (Test-InMorningSyncWindow)) {
                Write-Log "Past 9:01 AM morning sync window; stopping polls."
                break
            }
            Start-Sleep -Seconds ($MorningPollMinutes * 60)
            if (-not (Test-InMorningSyncWindow)) {
                Write-Log "Reached 9:01 AM cutoff during poll wait; stopping."
                break
            }
            Write-Log "Morning readiness poll attempt $attempt/$MorningPollMaxAttempts"
            Invoke-SyncPipelineCore
            $status = Get-MorningReadinessStatus
            Save-MorningReadinessStatus $status
            Write-Log ("Morning readiness: status={0} missing={1}" -f `
                $status.status, ($status.missing_fields -join ","))
            if ($status.status -eq "complete") {
                Write-Log "Morning readiness complete; workflow may proceed."
                break
            }
        }
        if ($status.status -ne "complete") {
            Write-Log "Morning readiness still partial after 9:01 AM window; sending nothing."
            exit 2
        }
    } elseif ($status.status -eq "partial") {
        Write-Log "Morning readiness partial outside 9:00-9:01 AM window; sync succeeded, readiness still partial."
    }

    Write-Log "Pipeline complete."
    exit 0
} catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    exit 1
}
