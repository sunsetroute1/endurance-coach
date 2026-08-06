#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Deploy the Jellyfin FFmpeg 9 program to the runtime location on this PC.
#>
[CmdletBinding()]
param(
    [string]$SourceRoot,
    [string]$TargetRoot = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9',
    [switch]$CreateDesktopShortcut
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$DeployScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SourceRoot) {
    $SourceRoot = Split-Path -Parent $DeployScriptRoot
}

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

if (-not (Test-Path $SourceRoot)) {
    throw "Source program not found: $SourceRoot"
}

Write-Step "Deploying Jellyfin FFmpeg 9 program"
Write-Step "Source: $SourceRoot"
Write-Step "Target: $TargetRoot"

New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null

$exclude = @('installer')
Get-ChildItem -Path $SourceRoot -Force | Where-Object {
    $_.Name -notin $exclude
} | ForEach-Object {
    $dest = Join-Path $TargetRoot $_.Name
    if ($_.PSIsContainer) {
        if (Test-Path $dest) {
            Remove-Item -Path $dest -Recurse -Force
        }
        Copy-Item -Path $_.FullName -Destination $dest -Recurse -Force
    }
    else {
        Copy-Item -Path $_.FullName -Destination $dest -Force
    }
}

$manifest = [ordered]@{
    name = 'Jellyfin FFmpeg 9'
    version = '1.1.0'
    deployed_at = (Get-Date -Format o)
    source_root = $SourceRoot
    target_root = $TargetRoot
    ffmpeg_root = 'C:\FFmpeg9'
    entrypoint = (Join-Path $TargetRoot 'Install-JellyfinFfmpeg9.ps1')
    repair = (Join-Path $TargetRoot 'Install-JellyfinFfmpeg9.ps1')
    test = (Join-Path $TargetRoot 'Install-JellyfinFfmpeg9.ps1')
}
$manifestPath = Join-Path $TargetRoot 'program.manifest.json'
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $manifestPath -Encoding UTF8

$legacyRoot = 'C:\ProgramData\Jellyfin\scripts'
@(
    @{ Name = 'Repair-Jellyfin-Ffmpeg9.ps1'; Action = 'Repair' },
    @{ Name = 'Test-JellyfinFfmpeg9.ps1'; Action = 'Test' }
) | ForEach-Object {
    $wrapperPath = Join-Path $legacyRoot $_.Name
    $wrapper = @"
@powershell -NoProfile -ExecutionPolicy Bypass -File "$TargetRoot\Install-JellyfinFfmpeg9.ps1" -Action $($_.Action) %*
"@
    Set-Content -Path $wrapperPath -Value $wrapper -Encoding ASCII
}

if ($CreateDesktopShortcut) {
    Write-Step 'Creating desktop shortcut'
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcutPath = Join-Path $desktop 'Jellyfin FFmpeg 9.lnk'
    $target = Join-Path $TargetRoot 'Install-JellyfinFfmpeg9.cmd'
    $wsh = New-Object -ComObject WScript.Shell
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $target
    $shortcut.WorkingDirectory = $TargetRoot
    $shortcut.IconLocation = "$env:SystemRoot\System32\imageres.dll,166"
    $shortcut.Description = 'Install or repair FFmpeg 9 integration for Jellyfin'
    $shortcut.Save()
    Write-Host "Desktop shortcut: $shortcutPath"
}

Write-Step 'Deploy complete'
Write-Host $TargetRoot

