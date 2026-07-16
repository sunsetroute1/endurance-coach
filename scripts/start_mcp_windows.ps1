# Start endurance-coach MCP server over HTTP (idempotent; safe for Task Scheduler).
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$WrapperLog = Join-Path $LogDir "mcp-startup.log"
$AppLog = Join-Path $LogDir "mcp.log"
$PidFile = Join-Path $LogDir "mcp.pid"
$McpPort = 8080

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $ProjectRoot

function Write-StartupLog([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    $line | Out-File -FilePath $WrapperLog -Append -Encoding utf8
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

function Wait-ForPort([int]$Port, [int]$TimeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortOpen $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

if (Test-PortOpen $McpPort) {
    Write-StartupLog "MCP already listening on port $McpPort"
    exit 0
}

if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-StartupLog "MCP process $oldPid still running"
        exit 0
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

Write-StartupLog "Waiting for PostgreSQL on port 5432..."
if (-not (Wait-ForPort 5432 30)) {
    Write-StartupLog "ERROR: PostgreSQL not available on port 5432"
    exit 1
}

Write-StartupLog "Starting MCP server (streamable-http on port $McpPort, app log: $AppLog)..."
$startCmd = "cd /d `"$ProjectRoot`" && python -c `"from endurance_coach.mcp.server import run; run()`" >> `"$AppLog`" 2>&1"
$proc = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList "/c", $startCmd `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru

$proc.Id | Out-File -FilePath $PidFile -Encoding ascii -NoNewline
if (-not (Wait-ForPort $McpPort 60)) {
    Write-StartupLog "ERROR: MCP did not open port $McpPort"
    exit 1
}

Write-StartupLog "Started MCP wrapper pid $($proc.Id) on http://127.0.0.1:$McpPort/mcp"
