# Ensure endurance-coach API, MCP, and Caddy stay healthy across reboots and VPN changes.
$ErrorActionPreference = "Continue"

. (Join-Path $PSScriptRoot "scheduled_task_helpers.ps1")

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "watchdog.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
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

function Wait-ForPort([int]$Port, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortOpen $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Invoke-StartScript([string]$Name, [string]$ScriptPath) {
    if (-not (Test-Path $ScriptPath)) {
        Write-Log "ERROR: missing $Name script at $ScriptPath"
        return
    }
    Write-Log "Starting $Name via $ScriptPath"
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    Invoke-SilentPowerShell -ScriptPath $ScriptPath -Wait
    $ErrorActionPreference = $previousErrorAction
}

function Get-EnvValue {
    param([string]$Key)
    $envPath = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envPath)) { return $null }
    foreach ($line in Get-Content $envPath) {
        if ($line -match "^\s*$([regex]::Escape($Key))=(.*)$") {
            return $Matches[1].Trim()
        }
    }
    return $null
}

function Get-PublicHealthUrl {
    $base = Get-EnvValue "PUBLIC_BASE_URL"
    if (-not $base) {
        return "http://127.0.0.1:8000/health"
    }
    return ($base.TrimEnd('/') + "/health")
}


Write-Log "Watchdog check started"

if (-not (Test-PortOpen 5432)) {
    Write-Log "PostgreSQL not ready; waiting up to 60s"
    if (-not (Wait-ForPort 5432 60)) {
        Write-Log "ERROR: PostgreSQL still unavailable; skipping app restarts"
        exit 1
    }
}

if (-not (Test-PortOpen 8000)) {
    Invoke-StartScript "API" (Join-Path $PSScriptRoot "start_api_windows.ps1")
}

if (-not (Test-PortOpen 8080)) {
    Invoke-StartScript "MCP" (Join-Path $PSScriptRoot "start_mcp_windows.ps1")
}

$apiUp = Test-PortOpen 8000
$mcpUp = Test-PortOpen 8080
Write-Log "Status api=$apiUp mcp=$mcpUp"

if (-not $apiUp -or -not $mcpUp) {
    exit 2
}

# Best-effort Caddy reload when the public site is unreachable locally.
$publicUrl = Get-PublicHealthUrl
try {
    $response = Invoke-WebRequest -Uri $publicUrl -UseBasicParsing -TimeoutSec 8
    if ($response.StatusCode -ne 200) {
        Write-Log "Public health returned $($response.StatusCode); reloading Caddy"
        Invoke-SilentPowerShell -ScriptPath (Join-Path $PSScriptRoot "reload_caddy.ps1") -Wait
    }
} catch {
    Write-Log "Public health check failed ($($_.Exception.Message)); reloading Caddy"
    Invoke-SilentPowerShell -ScriptPath (Join-Path $PSScriptRoot "reload_caddy.ps1") -Wait
}

exit 0
