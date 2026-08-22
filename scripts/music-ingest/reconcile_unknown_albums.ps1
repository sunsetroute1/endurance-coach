# Reconcile Navidrome "Unknown Album" entries via folder names, metadata, beets, and move.
param(
    [switch]$DryRun,
    [switch]$SkipBeets,
    [switch]$SkipDiskPass,
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
$LogFile = Join-Path $RepoRoot "logs\reconcile-unknown-albums.log"

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

Write-Log "Unknown Album reconciliation started"

$tagArgs = @($FolderTags, $MusicRoot, "--reconcile-unknown-albums")
if ($DryRun) { $tagArgs += "--dry-run" }
if (-not $SkipDiskPass) {
    & $Python @tagArgs 2>&1 | ForEach-Object { Write-Log $_ }
} else {
    Write-Log "Skipping disk tag pass (SkipDiskPass)"
}

if ($SkipBeets -or $DryRun) {
    Write-Log "Skipping beets import/move (DryRun or SkipBeets)"
} else {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = $BeetErrorAction
    $unknownDirs = Get-ChildItem $MusicRoot -Recurse -Directory -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq 'Unknown Album' -and
            $_.FullName -notmatch '\\Incoming\\|\\State\\|\\Quarantine\\'
        }

    Write-Log ("Beets autotag on {0} remaining Unknown Album folder(s)" -f @($unknownDirs).Count)
    foreach ($dir in $unknownDirs) {
        Write-Log "  beet import: $($dir.FullName)"
        $importOut = & $Beet import -q $dir.FullName 2>&1
        $importOut | Select-Object -Last 5 | ForEach-Object { Write-Log "    $_" }
        if ($LASTEXITCODE -ne 0) {
            Write-Log "    beet import exit $LASTEXITCODE (may already be cataloged)"
        }
    }

    Write-Log "beet fromfolder -w"
    & $Beet fromfolder -w 2>&1 | ForEach-Object { Write-Log $_ }

    Write-Log "beet move -a"
    & $Beet move -a 2>&1 | Select-Object -Last 20 | ForEach-Object { Write-Log $_ }

    Write-Log "beet fetchart -q"
    try {
        & $Beet fetchart -q 2>&1 | Select-Object -Last 10 | ForEach-Object { Write-Log $_ }
    } catch {
        Write-Log "beet fetchart warning: $($_.Exception.Message) (stale beets album entries may remain)"
    }
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        Write-Log "beet fetchart exit $LASTEXITCODE (continuing)"
    }
    $ErrorActionPreference = $prevEap
}

if ($RescanNavidrome -and -not $DryRun) {
    Write-Log "Navidrome rescan"
    & (Join-Path $PSScriptRoot "rescan_navidrome.ps1") 2>&1 | ForEach-Object { Write-Log $_ }
}

$remaining = @(Get-ChildItem $MusicRoot -Recurse -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq 'Unknown Album' -and $_.FullName -notmatch '\\Incoming\\|\\State\\|\\Quarantine\\' }).Count
Write-Log ("Done. Remaining Unknown Album folders: {0}. Log: {1}" -f $remaining, $LogFile)
