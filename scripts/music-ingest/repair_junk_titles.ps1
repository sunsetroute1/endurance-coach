# Repair junk titles (e.g. literal \1 from broken beets rewrite rules) across the library.
param(
    [switch]$DryRun,
    [switch]$RescanNavidrome,
    [switch]$SkipFolderTags,
    [switch]$NoRename
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Python = Join-Path $RepoRoot "services\music-ingest\.venv\Scripts\python.exe"
$Script = Join-Path $PSScriptRoot "repair_junk_titles.py"
$BeetsConfig = Join-Path $env:APPDATA "beets\config.yaml"

if (-not (Test-Path $Python)) {
    throw "Music ingest venv not found. Run install_music_ingest.ps1 first."
}

# Strip legacy rewrite rules that write literal \1 into tags.
if (Test-Path $BeetsConfig) {
    $beetsContent = Get-Content $BeetsConfig -Raw
    $beetsContent = $beetsContent -replace '(?m)^  (?:artist|album|albumartist|title) \^\d+\\\.?\s+\(\.\+\)\$: \\1\r?\n', ''
    [System.IO.File]::WriteAllText($BeetsConfig, $beetsContent.TrimEnd() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

$pyArgs = @($Script)
if ($DryRun) { $pyArgs += "--dry-run" }
if ($SkipFolderTags) { $pyArgs += "--skip-folder-tags" }
if ($NoRename) { $pyArgs += "--no-rename" }

& $Python @pyArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($RescanNavidrome -and -not $DryRun) {
    & (Join-Path $PSScriptRoot "rescan_navidrome.ps1") -Incremental
}
