# Idempotent repair (delegates to main program).
#Requires -RunAsAdministrator
param([switch]$Json)

$program = Join-Path $PSScriptRoot 'Install-JellyfinFfmpeg9.ps1'
if (-not (Test-Path $program)) {
    $program = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9\Install-JellyfinFfmpeg9.ps1'
}
$params = @{ Action = 'Repair'; Elevated = $true }
if ($Json) { $params.Json = $true }
& $program @params
exit $LASTEXITCODE
