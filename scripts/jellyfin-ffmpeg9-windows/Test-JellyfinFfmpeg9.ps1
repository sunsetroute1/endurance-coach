# Health check for Jellyfin FFmpeg 9 setup (delegates to main program).
param([switch]$Json)

$program = Join-Path $PSScriptRoot 'Install-JellyfinFfmpeg9.ps1'
if (-not (Test-Path $program)) {
    $program = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9\Install-JellyfinFfmpeg9.ps1'
}

$params = @{ Action = 'Test' }
if ($Json) { $params.Json = $true }
& $program @params
exit $LASTEXITCODE
