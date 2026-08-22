# Restart API and MCP so .env changes (e.g. API_SECRET_KEY) take effect.

$ErrorActionPreference = "Continue"

. (Join-Path $PSScriptRoot "scheduled_task_helpers.ps1")

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$coachHelpers = Join-Path $PSScriptRoot "coach-stack-helpers.ps1"
if (Test-Path $coachHelpers) {
    . $coachHelpers
    if (Test-CoachDockerMode) {
        $ok = Invoke-CoachDockerRecovery -Reason 'restart-app-services' -StartupWaitSec 40
        exit $(if ($ok) { 0 } else { 1 })
    }
}

$LogDir = Join-Path $ProjectRoot "logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null



function Write-RestartLog([string]$Message) {

    $line = "$(Get-Date -Format o) $Message"

    $logFile = Join-Path $LogDir "restart-services.log"

    $line | Out-File -FilePath $logFile -Append -Encoding utf8

}



function Stop-PortListener([int]$Port, [string]$Name) {

    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue

    foreach ($conn in $connections) {

        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue

        if ($proc) {

            Write-RestartLog "Stopping $Name listener pid $($proc.Id) on port $Port"

            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue

        }

    }

}



Stop-PortListener -Port 8000 -Name "API"

Stop-PortListener -Port 8080 -Name "MCP"



foreach ($pidFile in @("api.pid", "mcp.pid")) {

    $path = Join-Path $LogDir $pidFile

    if (Test-Path $path) {

        Remove-Item $path -Force -ErrorAction SilentlyContinue

    }

}



Start-Sleep -Seconds 2



$apiExit = Invoke-SilentPowerShell -ScriptPath (Join-Path $PSScriptRoot "start_api_windows.ps1") -Wait

if ($apiExit -ne 0) {

    $apiUp = $false

    try {

        $client = New-Object System.Net.Sockets.TcpClient

        $connect = $client.BeginConnect("127.0.0.1", 8000, $null, $null)

        $ready = $connect.AsyncWaitHandle.WaitOne(500)

        if ($ready -and $client.Connected) { $apiUp = $true }

        $client.Close()

    } catch {}

    if (-not $apiUp) { exit $apiExit }

}



$mcpExit = Invoke-SilentPowerShell -ScriptPath (Join-Path $PSScriptRoot "start_mcp_windows.ps1") -Wait

if ($mcpExit -ne 0) {

    $mcpUp = $false

    try {

        $client = New-Object System.Net.Sockets.TcpClient

        $connect = $client.BeginConnect("127.0.0.1", 8080, $null, $null)

        $ready = $connect.AsyncWaitHandle.WaitOne(500)

        if ($ready -and $client.Connected) { $mcpUp = $true }

        $client.Close()

    } catch {}

    if (-not $mcpUp) { exit $mcpExit }

}



Write-RestartLog "Restart complete"

exit 0

