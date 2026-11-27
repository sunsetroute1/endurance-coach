# Health probe for Automation Watchboard (delegates to main program).
$program = Join-Path $PSScriptRoot 'Install-JellyfinFfmpeg9.ps1'
if (-not (Test-Path $program)) {
    $program = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9\Install-JellyfinFfmpeg9.ps1'
}
& $program -Action Test -Json
exit $LASTEXITCODE
