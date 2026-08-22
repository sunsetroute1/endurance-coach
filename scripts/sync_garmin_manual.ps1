# Manual Garmin sync for desktop shortcuts (sync -> process -> analytics -> MCP-ready data).
param(
    [switch]$ActivitiesOnly,
    [switch]$FullSync,
    [string]$ApiBase = "http://localhost:8000"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "manual-garmin-sync.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Both([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
    Write-Host $Message
}

function Get-ApiSecretKey {
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) { return $null }
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*API_SECRET_KEY=(.+)$') {
            return $Matches[1].Trim()
        }
    }
    return $null
}

function Invoke-ApiPost([string]$Path, [hashtable]$Body) {
    $json = if ($Body.Count -gt 0) { $Body | ConvertTo-Json -Compress } else { "{}" }
    $headers = @{ "Content-Type" = "application/json" }
    $key = Get-ApiSecretKey
    if ($key) { $headers["Authorization"] = "Bearer $key" }
    return Invoke-RestMethod -Method POST -Uri "$ApiBase$Path" -Headers $headers -Body $json
}

try {
    Write-Both "Checking API at $ApiBase..."
    $null = Invoke-RestMethod -Method GET -Uri "$ApiBase/health" -TimeoutSec 10

    $syncBody = @{}
    if ($FullSync) { $syncBody.full_sync = $true }
    if ($ActivitiesOnly) { $syncBody.resource_types = @("activities") }

    Write-Both "Syncing Garmin..."
    $sync = Invoke-ApiPost "/api/v1/sync/garmin" $syncBody
    Write-Both ("  status={0}" -f $sync.status)
    Write-Both ("  synced={0}" -f ($sync.resources_synced | ConvertTo-Json -Compress))

    Write-Both "Processing normalized records..."
    $processLimit = if ($FullSync) { 500 } else { 100 }
    $process = Invoke-ApiPost "/api/v1/process" @{ limit = $processLimit }
    Write-Both ("  processed={0}" -f ($process.processed | ConvertTo-Json -Compress))

    if (-not $ActivitiesOnly) {
        Write-Both "Computing analytics..."
        $analytics = Invoke-ApiPost "/api/v1/analytics/compute" @{}
        Write-Both ("  families={0}" -f ($analytics.families -join ", "))
    }

    Write-Both "Done. MCP now has the latest synced Garmin data."
    Write-Host ""
    Write-Host "Log: $LogFile" -ForegroundColor DarkGray
    Start-Sleep -Seconds 4
    exit 0
} catch {
    Write-Both "ERROR: $($_.Exception.Message)"
    if ($_.ErrorDetails.Message) { Write-Both $_.ErrorDetails.Message }
    Write-Host ""
    Write-Host "Press Enter to close..."
    Read-Host | Out-Null
    exit 1
}
