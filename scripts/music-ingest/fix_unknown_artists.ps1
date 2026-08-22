# Backfill missing artist/title tags, consolidate junk folders, exclude quarantine from Navidrome, rescan.
param(
    [switch]$DryRun,
    [switch]$SkipNavidrome
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$IngestRoot = Join-Path $RepoRoot "services\music-ingest"
$Python = Join-Path $IngestRoot ".venv\Scripts\python.exe"
$FolderTags = Join-Path $IngestRoot "src\folder_tags.py"
$MusicRoot = "E:\Music"
$NdIgnore = Join-Path $MusicRoot ".ndignore"
$LogFile = Join-Path $RepoRoot "logs\fix-unknown-artists.log"

if (-not (Test-Path $Python)) {
    throw "Music ingest venv not found. Run install_music_ingest.ps1 first."
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile -Parent) | Out-Null
function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Host $Message
}

function Invoke-FolderTags([string[]]$ExtraArgs) {
    $args = @($FolderTags, $MusicRoot) + $ExtraArgs
    if ($DryRun) { $args += "--dry-run" }
    & $Python @args 2>&1 | ForEach-Object { Write-Log $_ }
}

$ndIgnoreBody = @"
# Paths excluded from Navidrome (ingest staging, quarantine, junk dumps)
Quarantine/
_/
Incoming/
State/
incomplete/
Non-Album/
"@

if (-not (Test-Path $NdIgnore) -or ((Get-Content $NdIgnore -Raw) -ne ($ndIgnoreBody + [Environment]::NewLine))) {
    if (-not $DryRun) {
        Set-Content -Path $NdIgnore -Value $ndIgnoreBody.TrimEnd() -Encoding utf8
        Write-Log "Wrote $NdIgnore"
    } else {
        Write-Log "Would write $NdIgnore"
    }
}

Write-Log "Step 1: quarantine stray audio files at library root"
Invoke-FolderTags @("--quarantine-root-loose")

Write-Log "Step 2: backfill artist/album/title tags from folder layout"
Invoke-FolderTags @()

Write-Log "Step 3: reconcile Unknown Album folders"
Invoke-FolderTags @("--reconcile-unknown-albums")

Write-Log "Step 4: consolidate junk artist folders (_/, 00 Roc, etc.)"
Invoke-FolderTags @("--consolidate-junk-artists")

if (-not $SkipNavidrome -and -not $DryRun) {
    Write-Log "Step 5: Navidrome full rescan with purge"
    $scanLog = Join-Path $RepoRoot "logs\navidrome-scan.log"
    & (Join-Path $PSScriptRoot "rescan_navidrome.ps1") 2>&1 | Tee-Object -FilePath $scanLog | Select-Object -Last 5 | ForEach-Object { Write-Host $_ }

    $count = docker exec navidrome sqlite3 /data/navidrome.db "SELECT COUNT(*) FROM media_file WHERE album_artist='[Unknown Artist]';" 2>$null
    if ($count) {
        Write-Log "[Unknown Artist] tracks remaining in Navidrome: $count"
    }
}

Write-Log "Done. Log: $LogFile"
