# Ensure endurance-coach API, MCP, and Caddy stay healthy across reboots and VPN changes.
$ErrorActionPreference = "Continue"

. (Join-Path $PSScriptRoot "scheduled_task_helpers.ps1")
. (Join-Path $PSScriptRoot "network_vpn_helpers.ps1")

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

$coachHelpers = Join-Path $PSScriptRoot "coach-stack-helpers.ps1"
$coachDocker = $false
if (Test-Path $coachHelpers) {
    . $coachHelpers
    $coachDocker = Test-CoachDockerMode
}

$vpnResult = Invoke-VpnNetworkWatchdog
if ($vpnResult.changed) {
    Write-Log "VPN/network transition handled (signature=$($vpnResult.current.signature))"
}

if ($coachDocker) {
    if (-not (Invoke-CoachDockerRecovery -Reason 'watchdog' -StartupWaitSec 30)) {
        Write-Log "ERROR: Coach Docker recovery failed"
        exit 1
    }
} else {
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
}

$apiUp = Test-PortOpen 8000
$mcpUp = Test-PortOpen 8080
Write-Log "Status api=$apiUp mcp=$mcpUp"

if (-not $apiUp -or -not $mcpUp) {
    exit 2
}

# If API was just restarted, catch up a missed Garmin sync (e.g. PC asleep at 9 AM).
$SyncLog = Join-Path $LogDir "sync-pipeline.log"
if (Test-Path $SyncLog) {
    $lastComplete = Select-String -Path $SyncLog -Pattern "Pipeline complete\." | Select-Object -Last 1
    $staleSync = $true
    if ($lastComplete -and $lastComplete.Line -match "^(\S+)") {
        try {
            $lastTime = [datetimeoffset]::Parse($Matches[1]).LocalDateTime
            $staleSync = ((Get-Date) - $lastTime).TotalHours -gt 6
        } catch {
            $staleSync = $true
        }
    }
    if ($staleSync) {
        Write-Log "Last successful Garmin sync is stale; running catch-up pipeline"
        $syncScript = Join-Path $PSScriptRoot "sync_garmin_pipeline.ps1"
        if (Test-Path $syncScript) {
            Invoke-SilentPowerShell -ScriptPath $syncScript -Wait | Out-Null
        }
    }
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

$musicFixScript = Join-Path $PSScriptRoot "music-ingest\fix_music_ingest.ps1"
if ((Test-Path $musicFixScript) -and -not (Test-Path (Join-Path $LogDir "music-ingest.pid"))) {
    Write-Log "Music ingest watcher pid missing; running repair"
    Invoke-SilentPowerShell -ScriptPath $musicFixScript -Wait | Out-Null
} elseif (Test-Path $musicFixScript) {
    $musicPidFile = Join-Path $LogDir "music-ingest.pid"
    $musicPid = Get-Content $musicPidFile -ErrorAction SilentlyContinue
    $musicRunning = $musicPid -and (Get-Process -Id $musicPid -ErrorAction SilentlyContinue)
    if (-not $musicRunning) {
        Write-Log "Music ingest watcher not running; running repair"
        Invoke-SilentPowerShell -ScriptPath $musicFixScript -Wait | Out-Null
    }
}

exit 0
