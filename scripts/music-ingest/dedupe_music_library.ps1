# Scan and remove duplicate tracks via beets (DB cleanup + delete extra files).
param(
    [switch]$Apply,
    [switch]$DbOnly,
    [switch]$RescanNavidrome
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Python = Join-Path $RepoRoot 'services\music-ingest\.venv\Scripts\python.exe'
$Script = Join-Path $PSScriptRoot 'dedupe_music_library.py'

if (-not (Test-Path $Python)) {
    throw 'Music ingest venv missing. Run install_music_ingest.ps1 first.'
}

$args = @($Script)
if ($Apply) { $args += '--apply' }
if ($DbOnly) { $args += '--skip-content' }

& $Python @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Apply -and $RescanNavidrome) {
    & (Join-Path $PSScriptRoot 'rescan_navidrome.ps1')
}
