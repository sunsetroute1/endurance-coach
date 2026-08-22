# Trigger a Navidrome library rescan (full scan by default).
param(
    [switch]$Incremental
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$LogDir = Join-Path $RepoRoot "logs"
$LogFile = Join-Path $LogDir "navidrome-scan.log"
$LockFile = Join-Path $LogDir "navidrome-scan.lock"
$DockerMarker = "C:\ProgramData\docker\media-stack\music-active.marker"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (Test-Path $LockFile) {
    $lockAge = (Get-Date) - (Get-Item $LockFile).LastWriteTime
    if ($lockAge.TotalHours -lt 2) {
        Write-Warning "Navidrome scan already in progress (lock age $([int]$lockAge.TotalMinutes)m); skipping"
        exit 0
    }
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType File -Force -Path $LockFile | Out-Null

try {
    $scanArgs = @("scan")
    if (-not $Incremental) {
        $scanArgs += "--full"
    }

    if ((Test-Path $DockerMarker) -and (docker ps -a --format "{{.Names}}" 2>$null | Select-String -Pattern "^navidrome$")) {
        # Running scan via docker exec while the server is up locks SQLite. Stop the
        # service, run a one-off scan container with the same volumes, then restart.
        $StackRoot = "C:\ProgramData\docker\media-stack"
        $NavData = Join-Path $StackRoot "config\navidrome"
        $MusicPath = "E:/Music"
        $envFile = Join-Path $StackRoot ".env"
        if (Test-Path $envFile) {
            Get-Content $envFile | ForEach-Object {
                if ($_ -match '^\s*MEDIA_MUSIC=(.+)$') { $MusicPath = $Matches[1].Trim() -replace '\\', '/' }
            }
        }
        $scanFlag = if ($Incremental) { "" } else { "--full" }
        $scanContainer = "navidrome-scan"
        Write-Host "Stopping Navidrome container for exclusive DB scan..."
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        docker stop navidrome 2>&1 | Out-Null
        docker rm -f $scanContainer 2>&1 | Out-Null
        Write-Host "Running one-off Docker Navidrome scan (PurgeMissing=full)..."
        try {
            docker run --rm --name $scanContainer `
                -v "${NavData}:/data" `
                -v "${MusicPath}:/music:ro" `
                -e ND_SCANNER_PURGEMISSING=full `
                deluan/navidrome:latest scan $scanFlag 2>&1 | Tee-Object -FilePath $LogFile
            $dockerExit = $LASTEXITCODE
        } finally {
            docker rm -f $scanContainer 2>&1 | Out-Null
        }
        Write-Host "Starting Navidrome container..."
        docker start navidrome 2>&1 | Out-Null
        $ready = $false
        for ($i = 0; $i -lt 30; $i++) {
            try {
                $null = Invoke-RestMethod -Uri "http://127.0.0.1:4533/ping" -TimeoutSec 3
                $ready = $true
                break
            } catch {
                Start-Sleep -Seconds 2
            }
        }
        if (-not $ready) {
            Write-Warning "Navidrome started but /ping did not respond within 60s"
        }
        $ErrorActionPreference = $prevEap
        if ($dockerExit -ne 0) {
            Write-Error "Docker Navidrome scan failed with exit code $dockerExit"
        }
        Write-Host "Docker Navidrome scan complete. Log: $LogFile"
        exit 0
    }

    $NavidromeExe = "C:\Navidrome\navidrome.exe"
    $NavidromeConfig = "C:\Navidrome\navidrome.toml"

    if (-not (Test-Path $NavidromeExe)) {
        Write-Error "Navidrome not found at $NavidromeExe and Docker navidrome is not running"
    }

    $nativeArgs = @("scan", "-c", $NavidromeConfig, "--logfile", $LogFile) + $scanArgs[1..($scanArgs.Length - 1)]
    Write-Host "Running: $NavidromeExe $($nativeArgs -join ' ')"
    & $NavidromeExe @nativeArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Navidrome scan failed with exit code $LASTEXITCODE"
    }

    Write-Host "Navidrome scan complete. Log: $LogFile"
} finally {
    Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
}
