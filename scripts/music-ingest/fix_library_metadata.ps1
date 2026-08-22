# Report and repair library tags: Unknown Album, [Cover], duplicates, MusicBrainz autotag.
param(
    [switch]$ReportOnly,
    [switch]$AutotagExisting,
    [switch]$UpdateMatched,
    [switch]$MoveReorganized,
    [switch]$FetchArt,
    [switch]$RescanNavidrome
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$IngestRoot = Join-Path $RepoRoot "services\music-ingest"
$Beet = Join-Path $IngestRoot ".venv\Scripts\beet.exe"
$MusicRoot = "E:\Music"
$BeetsTemplate = Join-Path $IngestRoot "config\beets-config.yaml"
$BeetsConfig = Join-Path $env:APPDATA "beets\config.yaml"
$ReportFile = Join-Path $RepoRoot "logs\library-metadata-report.txt"

if (-not (Test-Path $Beet)) {
    throw "beets not installed. Run install_music_ingest.ps1 first."
}

Copy-Item $BeetsTemplate $BeetsConfig -Force
$pluginPath = (Join-Path $IngestRoot "plugins") -replace '\\', '/'
[System.IO.File]::WriteAllText(
    $BeetsConfig,
    ((Get-Content $BeetsConfig -Raw) -replace 'MUSIC_INGEST_PLUGINPATH', $pluginPath).TrimEnd() + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false))
$pipelineEnv = Join-Path $IngestRoot "config\pipeline.env"
if (Test-Path $pipelineEnv) {
    $key = ""; $secret = ""
    foreach ($line in Get-Content $pipelineEnv) {
        if ($line -match '^\s*LASTFM_API_KEY=(.+)$') { $key = $Matches[1].Trim().Trim('"') }
        if ($line -match '^\s*LASTFM_API_SECRET=(.+)$') { $secret = $Matches[1].Trim().Trim('"') }
    }
    if ($key) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install_music_ingest.ps1") | Out-Null
    }
}

function Write-Report([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    $line | Out-File -FilePath $ReportFile -Append -Encoding utf8
    Write-Host $Message
}

New-Item -ItemType Directory -Force -Path (Split-Path $ReportFile -Parent) | Out-Null
"" | Out-File -FilePath $ReportFile -Encoding utf8
Write-Report "Library metadata report started"

$coverFolders = @()
$unknownAlbumFolders = @()
$merleFolders = @()

Get-ChildItem $MusicRoot -Recurse -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    $rel = $_.FullName.Substring($MusicRoot.Length).TrimStart('\')
    if ($rel -match '^Incoming\\|^State\\|^Quarantine\\') { return }
    if ($_.Name -eq '[Cover]') { $coverFolders += $rel }
    if ($_.Name -eq 'Unknown Album') { $unknownAlbumFolders += $rel }
    if ($_.Name -match 'Merle Haggard|Haggard') { $merleFolders += $rel }
}

Write-Report ("[Cover] album folders: {0}" -f $coverFolders.Count)
$coverFolders | Select-Object -First 25 | ForEach-Object { Write-Report "  $_" }
Write-Report ("Unknown Album folders: {0}" -f $unknownAlbumFolders.Count)
$unknownAlbumFolders | Select-Object -First 25 | ForEach-Object { Write-Report "  $_" }
Write-Report ("Merle/Haggard-related folders: {0}" -f $merleFolders.Count)
$merleFolders | ForEach-Object { Write-Report "  $_" }

Write-Report "Beets library stats:"
& $Beet stats 2>&1 | ForEach-Object { Write-Report $_ }

Write-Report "Duplicate albums (beets):"
& $Beet dup -a 2>&1 | Select-Object -First 40 | ForEach-Object { Write-Report $_ }

if ($ReportOnly) {
    Write-Report "ReportOnly complete: $ReportFile"
    exit 0
}

if ($AutotagExisting) {
    Write-Report "Importing/autotagging existing library (skips Incoming/State/Quarantine)..."
    Write-Report "This can take a long time on first run (~9600 tracks)."
    $artistDirs = Get-ChildItem $MusicRoot -Directory |
        Where-Object { $_.Name -notin @('Incoming', 'State', 'Quarantine') }
    foreach ($dir in $artistDirs) {
        Write-Report "Importing $($dir.Name)..."
        & $Beet import -q $dir.FullName
    }
}

if ($UpdateMatched) {
    Write-Report "Applying folder-name tags to matched items..."
    & $Beet fromfolder -w
    Write-Report "Updating matched albums from MusicBrainz..."
    & $Beet update -a
}

if ($MoveReorganized) {
    Write-Report "Moving files to match corrected tags..."
    & $Beet move -a
}

if ($FetchArt) {
    Write-Report "Fetching missing album art..."
    & $Beet fetchart -q
}

if ($RescanNavidrome) {
    Write-Report "Triggering Navidrome rescan..."
    & (Join-Path $PSScriptRoot "rescan_navidrome.ps1")
}

Write-Report "Done. Report: $ReportFile"
