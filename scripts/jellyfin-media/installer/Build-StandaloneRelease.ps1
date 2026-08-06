#Requires -Version 5.1
<#
.SYNOPSIS
  Refresh the public standalone release from scripts/jellyfin-media.
#>
[CmdletBinding()]
param(
    [string]$SourceRoot,
    [string]$TargetRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$InstallerRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$MediaRoot = Split-Path -Parent $InstallerRoot
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MediaRoot)
$ProjectsRoot = Split-Path -Parent $RepoRoot
if (-not $SourceRoot) { $SourceRoot = $MediaRoot }
if (-not $TargetRoot) { $TargetRoot = Join-Path $ProjectsRoot 'jellyfin-ffmpeg9-windows' }

if (-not (Test-Path $SourceRoot)) {
    throw "Source not found: $SourceRoot"
}

$coreFiles = @(
    'Install-JellyfinFfmpeg9.ps1',
    'Install-JellyfinFfmpeg9.cmd',
    'Repair-Jellyfin-Ffmpeg9.ps1',
    'Test-JellyfinFfmpeg9.ps1'
)

if (Test-Path $TargetRoot) {
    Remove-Item -Path $TargetRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path (Join-Path $TargetRoot 'lib') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $TargetRoot 'installer') | Out-Null

Copy-Item -Path (Join-Path $SourceRoot 'lib\*') -Destination (Join-Path $TargetRoot 'lib') -Recurse -Force
Copy-Item -Path (Join-Path $SourceRoot 'installer\Deploy-JellyfinFfmpeg9.ps1') -Destination (Join-Path $TargetRoot 'installer') -Force
foreach ($file in $coreFiles) {
    Copy-Item -Path (Join-Path $SourceRoot $file) -Destination (Join-Path $TargetRoot $file) -Force
}

$standaloneOnly = Join-Path $PSScriptRoot 'standalone-files'
if (Test-Path $standaloneOnly) {
    Get-ChildItem -Path $standaloneOnly -File | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination (Join-Path $TargetRoot $_.Name) -Force
    }
}

$installPs1 = Join-Path $TargetRoot 'Install-JellyfinFfmpeg9.ps1'
$content = Get-Content -Path $installPs1 -Raw -Encoding UTF8
$content = $content -replace 'Idempotent fix after Jellyfin update \(Watchboard Fix uses this\)\.', 'Re-apply settings after a Jellyfin server update.'
$content = $content -replace 'Health check JSON for Automation Watchboard\.', 'Machine-readable health check (exit 1 if repair is needed).'
$content = $content -replace "Write-Host 'Repair after Jellyfin update: Watchboard Jellyfin -> Fix, or run:'", "Write-Host 'After a Jellyfin update, run Repair.cmd or:'"
Set-Content -Path $installPs1 -Value $content -Encoding UTF8

$deployPs1 = Join-Path $TargetRoot 'installer\Deploy-JellyfinFfmpeg9.ps1'
$deploy = Get-Content -Path $deployPs1 -Raw -Encoding UTF8
$deploy = $deploy -replace "@\(\r?\n    @\{ Name = 'Repair-Jellyfin-Ffmpeg9\.ps1'; Action = 'Repair' \},\r?\n    @\{ Name = 'Test-JellyfinFfmpeg9\.ps1'; Action = 'Test' \},\r?\n    @\{ Name = 'Install-JellyfinFfmpeg9-Package\.ps1'; Action = 'Install' \}\r?\n\)", "@(`r`n    @{ Name = 'Repair-Jellyfin-Ffmpeg9.ps1'; Action = 'Repair' },`r`n    @{ Name = 'Test-JellyfinFfmpeg9.ps1'; Action = 'Test' }`r`n)"
Set-Content -Path $deployPs1 -Value $deploy -Encoding UTF8

$testPs1 = Join-Path $TargetRoot 'Test-JellyfinFfmpeg9.ps1'
Set-Content -Path $testPs1 -Value @'
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
'@ -Encoding UTF8

Write-Host "Standalone release refreshed: $TargetRoot"
