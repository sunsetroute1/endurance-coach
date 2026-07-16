# Start endurance-coach API on Windows (idempotent; safe for Task Scheduler).
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$WrapperLog = Join-Path $LogDir "api-startup.log"
$AppLog = Join-Path $LogDir "api.log"
$PidFile = Join-Path $LogDir "api.pid"
$ApiPort = 8000

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

if (Test-PortOpen $ApiPort) {
    Write-StartupLog "API already listening on port $ApiPort"
    exit 0
}

if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-StartupLog "API process $oldPid still running"
        exit 0
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

Write-StartupLog "Waiting for PostgreSQL on port 5432..."
if (-not (Wait-ForPort 5432 60)) {
    Write-StartupLog "ERROR: PostgreSQL not available on port 5432"
    exit 1
}

Write-StartupLog "Running migrations..."
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python -m alembic upgrade head 2>&1 | Out-File -FilePath $WrapperLog -Append -Encoding utf8
$ErrorActionPreference = $previousErrorAction
if ($LASTEXITCODE -ne 0) {
    Write-StartupLog "ERROR: alembic upgrade failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

Write-StartupLog "Starting uvicorn on 127.0.0.1:$ApiPort (app log: $AppLog)..."
$startCmd = "cd /d `"$ProjectRoot`" && python -m uvicorn endurance_coach.api.main:app --host 127.0.0.1 --port $ApiPort >> `"$AppLog`" 2>&1"
$proc = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList "/c", $startCmd `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru

$proc.Id | Out-File -FilePath $PidFile -Encoding ascii -NoNewline
if (-not (Wait-ForPort $ApiPort 60)) {
    Write-StartupLog "ERROR: API did not open port $ApiPort"
    exit 1
}

Write-StartupLog "Started API wrapper pid $($proc.Id)"
