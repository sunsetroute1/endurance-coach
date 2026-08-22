# Full library cleanup: quarantine DRM, consolidate junk artists, autotag Singles, rescan.
param(
    [switch]$DryRun,
    [switch]$SkipAutotag,
    [switch]$SkipNavidrome
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
$LogFile = Join-Path $RepoRoot "logs\cleanup-music-library.log"

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

Write-Log "Music library cleanup started"

function Invoke-FolderTags([string[]]$ExtraArgs) {
    $args = @($FolderTags, $MusicRoot) + $ExtraArgs
    if ($DryRun) { $args += "--dry-run" }
    & $Python @args 2>&1 | ForEach-Object { Write-Log $_ }
}

Write-Log "Step 1: quarantine DRM .m4p and unparseable Non-Album files"
Invoke-FolderTags @("--quarantine-unsupported")

Write-Log "Step 2: organize any remaining parseable Non-Album files"
Invoke-FolderTags @("--organize-non-album")

Write-Log "Step 3: consolidate junk artist folders into Artist/Singles"
Invoke-FolderTags @("--consolidate-junk-artists")

Write-Log "Step 4: remove art-only Unknown Album folders"
Invoke-FolderTags @("--remove-art-unknown-albums")

if ($SkipAutotag -or $DryRun) {
    Write-Log "Skipping Singles autotag (DryRun or SkipAutotag)"
} else {
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = $BeetErrorAction

    $singlesDirs = Get-ChildItem $MusicRoot -Recurse -Directory -Filter "Singles" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.FullName -notmatch '\\Incoming\\|\\State\\|\\Quarantine\\|\\Non-Album\\' -and
            @(Get-ChildItem -LiteralPath $_.FullName -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Extension -match '^\.(mp3|flac|m4a|ogg|opus|wma|aac|alac)$' }).Count -gt 0
        }

    Write-Log ("Step 5: MusicBrainz autotag on {0} Singles folder(s)" -f @($singlesDirs).Count)
    $i = 0
    foreach ($dir in $singlesDirs) {
        $i++
        if ($i % 50 -eq 0) {
            Write-Log "  autotag progress: $i / $($singlesDirs.Count)"
        }
        $null = & $Beet import -q -s $dir.FullName 2>&1
    }

    Write-Log "beet move -a"
    & $Beet move -a 2>&1 | Select-Object -Last 15 | ForEach-Object { Write-Log $_ }

    $ErrorActionPreference = $prevEap
}

if (-not $SkipNavidrome -and -not $DryRun) {
    Write-Log "Step 6: Navidrome rescan"
    & (Join-Path $PSScriptRoot "rescan_navidrome.ps1") 2>&1 | ForEach-Object { Write-Log $_ }
}

$remainingNonAlbum = @(Get-ChildItem (Join-Path $MusicRoot "Non-Album") -File -ErrorAction SilentlyContinue).Count
$remainingUnknown = @(Get-ChildItem $MusicRoot -Recurse -Directory -Filter "Unknown Album" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notmatch '\\Incoming\\|\\State\\|\\Quarantine\\' }).Count
Write-Log ("Done. Non-Album files: {0}, Unknown Album folders: {1}. Log: {2}" -f $remainingNonAlbum, $remainingUnknown, $LogFile)
