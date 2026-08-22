# Recover music ingest: watcher, slskd, Navidrome, beets, and rescan library index.
param([switch]$SkipNavidromeRescan)

$ErrorActionPreference = "Stop"
$CoachRoot = Split-Path -Parent $PSScriptRoot
$fixMusic = Join-Path $CoachRoot "scripts\music-ingest\fix_music_ingest.ps1"
$rescan = Join-Path $CoachRoot "scripts\music-ingest\rescan_navidrome.ps1"
$bootMedia = "C:\ProgramData\docker\media-stack\scripts\boot-start-media-stack.ps1"

if (Test-Path $bootMedia) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootMedia
}
if (Test-Path $fixMusic) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $fixMusic
}
if (-not $SkipNavidromeRescan -and (Test-Path $rescan)) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $rescan
}
