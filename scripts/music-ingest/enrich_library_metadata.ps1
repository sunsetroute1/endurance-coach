# Backfill missing album art and genres for the existing beets library.
param(
    [switch]$ArtOnly,
    [switch]$GenreOnly,
    [switch]$RescanNavidrome
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$IngestRoot = Join-Path $RepoRoot "services\music-ingest"
$Beet = Join-Path $IngestRoot ".venv\Scripts\beet.exe"

if (-not (Test-Path $Beet)) {
    throw "beets not installed. Run install_music_ingest.ps1 first."
}

$runArt = -not $GenreOnly
$runGenre = -not $ArtOnly

if ($runArt) {
    Write-Host "==> Fetching missing album art (multi-source fetchart)..."
    & $Beet fetchart -q
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "beet fetchart exited $LASTEXITCODE (some albums may still lack art)"
    }
}

if ($runGenre) {
    Write-Host "==> Filling missing genres from Last.fm (when API key configured)..."
    & $Beet lastgenre -a
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "beet lastgenre exited $LASTEXITCODE (often means Last.fm key missing)"
    }
}

if ($RescanNavidrome) {
    Write-Host "==> Triggering Navidrome library rescan..."
    & (Join-Path $PSScriptRoot "rescan_navidrome.ps1")
}

Write-Host "Metadata enrichment complete."
