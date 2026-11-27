# Repair music ingestion: beets venv, scheduled tasks, slskd, and the realtime watcher.
param(
    [switch]$ReinstallTasks,
    [switch]$RescanNavidrome
)

$ErrorActionPreference = "Stop"

. (Join-Path (Split-Path $PSScriptRoot -Parent) "scheduled_task_helpers.ps1")

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$IngestRoot = Join-Path $RepoRoot "services\music-ingest"
$VenvPython = Join-Path $IngestRoot ".venv\Scripts\python.exe"
$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir "fix-music-ingest.log"
$PidFile = Join-Path $LogDir "music-ingest.pid"
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

function Test-MusicWatcherRunning {
    if (-not (Test-Path $PidFile)) { return $false }
    $pidValue = Get-Content $PidFile -ErrorAction SilentlyContinue
    if (-not $pidValue) { return $false }
    return $null -ne (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
}

function Clear-StaleMusicWatcherPid {
    if (-not (Test-Path $PidFile)) { return }
    if (Test-MusicWatcherRunning) { return }
    Write-Log "Removing stale music watcher pid file"
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}

Write-Log "Music ingest fix started"
$changed = $false
$SlskdIdleMarker = "C:\ProgramData\slskd-idle\intentionally-stopped.marker"
$slskdIntentionallyStopped = Test-Path $SlskdIdleMarker

if (-not (Test-Path $VenvPython)) {
    Write-Log "Music ingest venv missing; running install_music_ingest.ps1"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install_music_ingest.ps1")
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: install_music_ingest failed with exit $LASTEXITCODE"
        exit 1
    }
    $changed = $true
} elseif ($ReinstallTasks) {
    Write-Log "Re-registering music ingest scheduled tasks"
    & (Join-Path $PSScriptRoot "install_music_watcher_startup.ps1")
    & (Join-Path $PSScriptRoot "install_music_ingest_fallback.ps1")
    $changed = $true
}

$scanLock = Join-Path $LogDir "navidrome-scan.lock"
$navidromeDown = -not (Test-PortOpen 4533)
$slskdDown = (-not $slskdIntentionallyStopped) -and -not (Test-PortOpen 5030)
if ($navidromeDown -and (Test-Path $scanLock)) {
    Write-Log "Navidrome scan in progress; leaving the server stopped until that scan finishes"
} elseif ($slskdDown -or $navidromeDown) {
    $changed = $true
    $dockerHelpers = 'C:\ProgramData\docker\media-stack\scripts\docker-stack-helpers.ps1'
    if ((Test-Path 'C:\ProgramData\docker\media-stack\music-active.marker') -and (Test-Path $dockerHelpers)) {
        Write-Log 'Starting Docker music stack (slskd + Navidrome)...'
        . $dockerHelpers
        if (Get-Command Invoke-DockerMediaStackRecovery -ErrorAction SilentlyContinue) {
            Invoke-DockerMediaStackRecovery -Reason 'music-ingest-fix' -StartupWaitSec 30 | Out-Null
        }
    } else {
        if (-not $slskdIntentionallyStopped -and -not (Test-PortOpen 5030)) {
            Write-Log "Starting slskd..."
            $slskdExit = Invoke-SilentPowerShell -ScriptPath (Join-Path $RepoRoot "scripts\start_slskd_windows.ps1") -Wait
            $slskdReady = $false
            for ($i = 0; $i -lt 30; $i++) {
                if (Test-PortOpen 5030) {
                    $slskdReady = $true
                    break
                }
                Start-Sleep -Seconds 1
            }
            if (-not $slskdReady) {
                Write-Log "WARNING: slskd still not listening on 5030 (exit=$slskdExit)"
            }
        }

        $NavidromeExe = "C:\Navidrome\navidrome.exe"
        if (-not (Test-PortOpen 4533) -and (Test-Path $NavidromeExe)) {
            Write-Log "Starting native Navidrome..."
            $navStdout = Join-Path $LogDir "navidrome.stdout.log"
            $navStderr = Join-Path $LogDir "navidrome.stderr.log"
            Start-Process -FilePath $NavidromeExe -WorkingDirectory "C:\Navidrome" -WindowStyle Hidden `
                -RedirectStandardOutput $navStdout -RedirectStandardError $navStderr | Out-Null
            Start-Sleep -Seconds 2
        }
    }
}

$RescanScript = Join-Path $PSScriptRoot "rescan_navidrome.ps1"
if ($RescanNavidrome -and (Test-Path $RescanScript) -and (Test-PortOpen 4533)) {
    Write-Log "Triggering Navidrome full rescan (-RescanNavidrome)..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $RescanScript
    if ($LASTEXITCODE -ne 0) {
        Write-Log "WARNING: Navidrome rescan failed with exit $LASTEXITCODE"
    }
} elseif (-not (Test-PortOpen 4533)) {
    Write-Log "Navidrome not running; run rescan_navidrome.ps1 after it starts"
} else {
    Write-Log "Navidrome up; skipping rescan (heal_music_ingest or -RescanNavidrome to scan)"
}

Clear-StaleMusicWatcherPid

if (-not (Test-MusicWatcherRunning)) {
    Write-Log "Starting music ingest watcher..."
    & (Join-Path $PSScriptRoot "start_music_watcher.ps1")
    $changed = $true
    Start-Sleep -Seconds 2
    if (-not (Test-MusicWatcherRunning)) {
        Write-Log "ERROR: music watcher failed to start"
        exit 1
    }
} else {
    $runningPid = Get-Content $PidFile
    Write-Log "Music ingest watcher already running (PID $runningPid)"
}

# A beets smoke test always follows with an exclusive Navidrome rescan, which
# takes the music server offline. Skip it when this pass did not change anything.
if ($changed) {
    Write-Log "Running beets smoke-test scan..."
    & (Join-Path $PSScriptRoot "run_beets_import.ps1") -ScanOnce
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: beets scan failed with exit $LASTEXITCODE"
        exit $LASTEXITCODE
    }
} else {
    Write-Log "Music ingest already in the expected state; skipped beets scan so Navidrome stays up"
}

$watcherPid = Get-Content $PidFile -ErrorAction SilentlyContinue
$beetsState = if ($changed) { "ok" } else { "skipped" }
Write-Log ("Fix complete: watcher={0} slskd={1} navidrome={2} beets={3}" -f `
    $watcherPid, (Test-PortOpen 5030), (Test-PortOpen 4533), $beetsState)
exit 0
