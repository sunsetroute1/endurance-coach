# Renumber album tracks sequentially from filename order (fixes duplicate/missing track tags).
param(
    [switch]$DryRun,
    [switch]$RescanNavidrome,
    [switch]$NoRename
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Python = Join-Path $RepoRoot "services\music-ingest\.venv\Scripts\python.exe"
$FolderTags = Join-Path $RepoRoot "services\music-ingest\src\folder_tags.py"

if (-not (Test-Path $Python)) {
    throw "Music ingest venv not found. Run install_music_ingest.ps1 first."
}

$pyArgs = @($FolderTags, "E:\Music", "--repair-track-order")
if ($DryRun) { $pyArgs += "--dry-run" }

& $Python @pyArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($RescanNavidrome -and -not $DryRun) {
    & (Join-Path $PSScriptRoot "rescan_navidrome.ps1") -Incremental
}
