# Repair endurance-coach automation: tasks, API/MCP, and Garmin sync pipeline.
# Safe to run from watchdog board / desktop shortcut (no admin required for core fix).
param(
    [switch]$UpdateTools
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "scheduled_task_helpers.ps1")

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "fix-services.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
    Write-Host $Message
}

function Test-PortOpen([int]$Port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $connect = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ready = $connect.AsyncWaitHandle.WaitOne(500)
        if ($ready -and $client.Connected) {
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

Write-Log "Fix script started"

$coachHelpers = Join-Path $PSScriptRoot "coach-stack-helpers.ps1"
if (Test-Path $coachHelpers) {
    . $coachHelpers
}

if ($UpdateTools) {
    Write-Log "Running silent elevated tool updates..."
    $updateScript = Join-Path $PSScriptRoot "update_tools_suite.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File $updateScript
    $updateExit = $LASTEXITCODE
    Write-Log "Tool update suite exit=$updateExit"
    if ($updateExit -ne 0) {
        exit $updateExit
    }
}

if ((Get-Command Test-CoachDockerMode -ErrorAction SilentlyContinue) -and (Test-CoachDockerMode)) {
    Write-Log "Coach Docker mode active; recovering compose stack"
    if (-not (Invoke-CoachDockerRecovery -Reason 'fix-services' -StartupWaitSec 40)) {
        Write-Log "ERROR: Coach Docker recovery failed"
        exit 1
    }
    Write-Log "Coach Docker stack healthy"

    Write-Log "Re-registering scheduled tasks (Docker-safe)..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install_all_services.ps1")
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: install_all_services failed with exit $LASTEXITCODE"
        exit 1
    }

    Write-Log "Running Garmin sync pipeline..."
    $syncExit = Invoke-SilentPowerShell -ScriptPath (Join-Path $PSScriptRoot "sync_garmin_pipeline.ps1") -Wait
    Write-Log "Garmin sync pipeline exit=$syncExit"
    if ($syncExit -ne 0) {
        exit $syncExit
    }

    $musicFixScript = Join-Path $PSScriptRoot "music-ingest\fix_music_ingest.ps1"
    if (Test-Path $musicFixScript) {
        Write-Log "Running music ingest repair..."
        $musicExit = Invoke-SilentPowerShell -ScriptPath $musicFixScript -Wait
        Write-Log "Music ingest fix exit=$musicExit"
        if ($musicExit -ne 0) {
            exit $musicExit
        }
    }

    Write-Log "Fix complete (Docker mode): api=True mcp=True sync=ok"
    exit 0
}

Write-Log "Re-registering scheduled tasks..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install_all_services.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Log "ERROR: install_all_services failed with exit $LASTEXITCODE"
    exit 1
}

if (-not (Test-PortOpen 5432)) {
    Write-Log "ERROR: PostgreSQL is not listening on port 5432"
    exit 1
}

if (-not (Test-PortOpen 8000)) {
    Write-Log "Starting API..."
    $apiExit = Invoke-SilentPowerShell -ScriptPath (Join-Path $PSScriptRoot "start_api_windows.ps1") -Wait
    if (-not (Test-PortOpen 8000)) {
        Write-Log "ERROR: API failed to start (exit=$apiExit)"
        exit 1
    }
}

if (-not (Test-PortOpen 8080)) {
    Write-Log "Starting MCP..."
    $mcpExit = Invoke-SilentPowerShell -ScriptPath (Join-Path $PSScriptRoot "start_mcp_windows.ps1") -Wait
    if (-not (Test-PortOpen 8080)) {
        Write-Log "ERROR: MCP failed to start (exit=$mcpExit)"
        exit 1
    }
}

Write-Log "Running Garmin sync pipeline..."
$syncExit = Invoke-SilentPowerShell -ScriptPath (Join-Path $PSScriptRoot "sync_garmin_pipeline.ps1") -Wait
Write-Log "Garmin sync pipeline exit=$syncExit"
if ($syncExit -ne 0) {
    exit $syncExit
}

$musicFixScript = Join-Path $PSScriptRoot "music-ingest\fix_music_ingest.ps1"
if (Test-Path $musicFixScript) {
    Write-Log "Running music ingest repair..."
    $musicExit = Invoke-SilentPowerShell -ScriptPath $musicFixScript -Wait
    Write-Log "Music ingest fix exit=$musicExit"
    if ($musicExit -ne 0) {
        exit $musicExit
    }
}

Write-Log "Fix complete: api=True mcp=True sync=ok music=ok"
exit 0
