# Download Navidrome metadata plugins (Cover Art Archive, etc.) into DataFolder/plugins.
# Note: Navidrome plugins fetch album art automatically; they do NOT support manual upload.
# For manual album covers, use set_album_cover.ps1 (writes cover.jpg into the album folder).
# Built-in UI upload (EnableArtworkUpload) works for artists, playlists, and internet radio only.$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$DockerMarker = "C:\ProgramData\docker\media-stack\music-active.marker"
$DockerNavData = "C:\ProgramData\docker\media-stack\config\navidrome"
$NativeNavData = "C:\Navidrome\data"

$NavData = if ((Test-Path $DockerMarker) -and (Test-Path $DockerNavData)) {
    $DockerNavData
} else {
    $NativeNavData
}

$PluginsDir = Join-Path $NavData "plugins"
New-Item -ItemType Directory -Force -Path $PluginsDir | Out-Null

$Plugins = @(
    @{
        Name = "coverartarchive"
        Url  = "https://github.com/sunsetroute1/navidrome-coverartarchive-plugin/releases/latest/download/coverartarchive.ndp"
    }
)

function Install-NavidromePlugin {
    param(
        [string]$Name,
        [string]$Url
    )

    $dest = Join-Path $PluginsDir "$Name.ndp"
    $tmp = Join-Path $env:TEMP "navidrome-$Name.ndp"
    Write-Host "Downloading $Name plugin..."
    Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -TimeoutSec 120
    Copy-Item -Path $tmp -Destination $dest -Force
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    Write-Host "Installed $dest"
}

foreach ($plugin in $Plugins) {
    Install-NavidromePlugin -Name $plugin.Name -Url $plugin.Url
}

Write-Host ""
Write-Host "Navidrome plugins installed to $PluginsDir"
Write-Host "Restart Navidrome, then enable plugins under Settings -> Plugins if needed."
