# Write album tags from parent folder when artist is already known.
param(
    [switch]$DryRun,
    [switch]$UnknownAlbumOnly,
    [switch]$BracketAlbumsOnly,
    [switch]$RescanNavidrome
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Python = Join-Path $RepoRoot "services\music-ingest\.venv\Scripts\python.exe"
$Script = Join-Path $RepoRoot "services\music-ingest\src\folder_tags.py"
$MusicRoot = "E:\Music"

if (-not (Test-Path $Python)) {
    throw "Music ingest venv not found. Run install_music_ingest.ps1 first."
}

$pyArgs = @($Script, $MusicRoot)
if ($DryRun) { $pyArgs += "--dry-run" }
if ($UnknownAlbumOnly) { $pyArgs += "--unknown-album-only" }
if ($BracketAlbumsOnly) { $pyArgs += "--bracket-albums-only" }

& $Python @pyArgs

if ($RescanNavidrome -and -not $DryRun) {
    & (Join-Path $PSScriptRoot "rescan_navidrome.ps1")
}
