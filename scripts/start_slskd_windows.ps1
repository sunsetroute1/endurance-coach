# Start slskd (Soulseek daemon) bound to localhost; Caddy proxies public HTTPS.
$ErrorActionPreference = "Stop"

$SlskdExe = "C:\slskd\slskd.exe"
$AppDir = "C:\slskd\data"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$WrapperLog = Join-Path $LogDir "slskd-startup.log"
$PidFile = Join-Path $LogDir "slskd.pid"
$SecretsFile = "C:\slskd\slskd.secrets.env"

New-Item -ItemType Directory -Force -Path $LogDir, $AppDir | Out-Null

function Write-StartupLog([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    $line | Out-File -FilePath $WrapperLog -Append -Encoding utf8
}

if (-not (Test-Path $SlskdExe)) {
    Write-StartupLog "ERROR: slskd binary not found at $SlskdExe"
    throw "slskd binary not found at $SlskdExe"
}

if (Test-Path $PidFile) {
    $oldPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-StartupLog "slskd already running (PID $oldPid)"
        exit 0
    }
}

if (Test-Path $SecretsFile) {
    Get-Content $SecretsFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -notmatch '^\s*([^=]+)=(.*)$') { return }
        $name = $Matches[1].Trim()
        $value = $Matches[2].Trim().Trim('"')
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

$args = @("--app-dir", $AppDir)
$stdoutLog = Join-Path $LogDir "slskd.stdout.log"
$stderrLog = Join-Path $LogDir "slskd.stderr.log"
$proc = Start-Process -FilePath $SlskdExe -ArgumentList $args -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
$proc.Id | Out-File -FilePath $PidFile -Encoding ascii -NoNewline
Write-StartupLog "Started slskd (PID $($proc.Id)); stdout=$stdoutLog stderr=$stderrLog"
