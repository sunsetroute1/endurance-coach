# Set or replace album cover art on disk (cover.jpg + optional embed via beets).
# Navidrome has no plugin for in-UI album cover upload; it reads cover.* from album folders.
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$AlbumPath,

    [Parameter(Mandatory = $true, Position = 1)]
    [string]$ImagePath,

    [switch]$Embed,
    [switch]$RescanNavidrome
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Beet = Join-Path $RepoRoot "services\music-ingest\.venv\Scripts\beet.exe"

$album = (Resolve-Path $AlbumPath).Path
$image = (Resolve-Path $ImagePath).Path

if (-not (Test-Path $album -PathType Container)) {
    throw "Album folder not found: $AlbumPath"
}
if (-not (Test-Path $image -PathType Leaf)) {
    throw "Image file not found: $ImagePath"
}

$ext = [System.IO.Path]::GetExtension($image).ToLowerInvariant()
if ($ext -notin @(".jpg", ".jpeg", ".png", ".webp", ".gif")) {
    throw "Unsupported image type: $ext (use jpg, png, webp, or gif)"
}

$dest = Join-Path $album "cover.jpg"
Copy-Item -Path $image -Destination $dest -Force
Write-Host "Wrote $dest"

if ($Embed -and (Test-Path $Beet)) {
    Write-Host "Embedding cover art into tracks with beets..."
    & $Beet embedart -a $album
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "beet embedart exited $LASTEXITCODE"
    }
}

if ($RescanNavidrome) {
    & (Join-Path $PSScriptRoot "rescan_navidrome.ps1") -Incremental
}

Write-Host "Done. Navidrome will pick up cover.jpg on the next scan (or run with -RescanNavidrome)."
