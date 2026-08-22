# Move beets Non-Album singletons into Artist/Singles/ with tags from filenames.
param(
    [switch]$DryRun,
    [switch]$SkipBeets,
    [switch]$RescanNavidrome
)

$ErrorActionPreference = "Stop"
$BeetErrorAction = "Continue"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$IngestRoot = Join-Path $RepoRoot "services\music-ingest"
$Python = Join-Path $IngestRoot ".venv\Scripts\python.exe"
$Beet = Join-Path $IngestRoot ".venv\Scripts\beet.exe"
$FolderTags = Join-Path $IngestRoot "src\folder_tags.py"
$BeetsTemplate = Join-Path $IngestRoot "config\beets-config.yaml"
$BeetsConfig = Join-Path $env:APPDATA "beets\config.yaml"
$MusicRoot = "E:\Music"
$LogFile = Join-Path $RepoRoot "logs\organize-non-album.log"

if (-not (Test-Path $Python)) {
    throw "Music ingest venv not found. Run install_music_ingest.ps1 first."
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile -Parent) | Out-Null
function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    Write-Host $Message
}

Copy-Item $BeetsTemplate $BeetsConfig -Force
$pluginPath = (Join-Path $IngestRoot "plugins") -replace '\\', '/'
[System.IO.File]::WriteAllText(
    $BeetsConfig,
    ((Get-Content $BeetsConfig -Raw) -replace 'MUSIC_INGEST_PLUGINPATH', $pluginPath).TrimEnd() + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false))

Write-Log "Non-Album organization started"

$tagArgs = @($FolderTags, $MusicRoot, "--organize-non-album")
if ($DryRun) { $tagArgs += "--dry-run" }
& $Python @tagArgs 2>&1 | ForEach-Object { Write-Log $_ }

# Remove leftover empty Unknown Album folders.
$emptyUnknown = Get-ChildItem $MusicRoot -Recurse -Directory -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -eq 'Unknown Album' -and
        $_.FullName -notmatch '\\Incoming\\|\\State\\|\\Quarantine\\' -and
        -not (Get-ChildItem $_.FullName -Force -ErrorAction SilentlyContinue)
    }
foreach ($dir in $emptyUnknown) {
    if (-not $DryRun) {
        Remove-Item $dir.FullName -Force
    }
    Write-Log "Removed empty Unknown Album folder: $($dir.FullName)"
}

if ($SkipBeets -or $DryRun) {
    Write-Log "Skipping beets import (DryRun or SkipBeets)"
} else {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = $BeetErrorAction

    $singlesDirs = Get-ChildItem $MusicRoot -Recurse -Directory -Filter "Singles" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\Incoming\\|\\State\\|\\Quarantine\\|\\Non-Album\\' }

    Write-Log ("Beets import on {0} Singles folder(s)" -f @($singlesDirs).Count)
    foreach ($dir in $singlesDirs) {
        Write-Log "  beet import: $($dir.FullName)"
        $importOut = & $Beet import -q $dir.FullName 2>&1
        $importOut | Select-Object -Last 3 | ForEach-Object { Write-Log "    $_" }
    }

    Write-Log "beet move -a"
    & $Beet move -a 2>&1 | Select-Object -Last 15 | ForEach-Object { Write-Log $_ }

    $ErrorActionPreference = $prevEap
}

if ($RescanNavidrome -and -not $DryRun) {
    Write-Log "Navidrome rescan"
    & (Join-Path $PSScriptRoot "rescan_navidrome.ps1") 2>&1 | ForEach-Object { Write-Log $_ }
}

$remainingNonAlbum = @(Get-ChildItem (Join-Path $MusicRoot "Non-Album") -File -ErrorAction SilentlyContinue).Count
$remainingUnknown = @(Get-ChildItem $MusicRoot -Recurse -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq 'Unknown Album' -and $_.FullName -notmatch '\\Incoming\\|\\State\\|\\Quarantine\\' }).Count
Write-Log ("Done. Non-Album files left: {0}, Unknown Album folders: {1}. Log: {2}" -f $remainingNonAlbum, $remainingUnknown, $LogFile)
