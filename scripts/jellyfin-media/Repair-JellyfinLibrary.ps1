#Requires -Version 5.1
<#
.SYNOPSIS
  Repair Jellyfin library duplicates and fix Alien collection metadata.
#>
[CmdletBinding()]
param(
    [switch]$WhatIf,
    [switch]$SkipLibraryScan
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$JellyfinData = 'C:\ProgramData\Jellyfin\Server\data'
$DbPath = Join-Path $JellyfinData 'jellyfin.db'
$CollectionsRoot = Join-Path $JellyfinData 'collections'
$AlienCollectionDir = Join-Path $CollectionsRoot 'Alien Collection [boxset]'
$AlienCollectionXml = Join-Path $AlienCollectionDir 'collection.xml'
$BackupDir = 'C:\ProgramData\Jellyfin\backups\library-repair'
$LogFile = 'C:\ProgramData\Jellyfin\logs\jellyfin-library-repair.log'
$RepairPy = Join-Path $PSScriptRoot 'repair_jellyfin_library.py'

function Write-Log([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format o), $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $Message
}

function Stop-JellyfinForRepair {
    $names = @('jellyfin', 'Jellyfin.Windows.Tray')
    foreach ($name in $names) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
            Write-Log "Stopping $($_.ProcessName) PID $($_.Id)"
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 3
}

function Start-JellyfinAfterRepair {
    $tray = 'C:\Program Files\Jellyfin\Server\jellyfin-windows-tray\Jellyfin.Windows.Tray.exe'
    if (Test-Path $tray) {
        Start-Process -FilePath $tray | Out-Null
        Write-Log 'Started Jellyfin tray'
    }
}

if (-not (Test-Path $RepairPy)) {
    throw "Missing repair script: $RepairPy"
}

New-Item -ItemType Directory -Force -Path $BackupDir, (Split-Path $LogFile -Parent) | Out-Null
Write-Log '=== Jellyfin library repair start ==='

Stop-JellyfinForRepair

$backup = Join-Path $BackupDir ('jellyfin.db.{0}.bak' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
Copy-Item -Path $DbPath -Destination $backup -Force
Write-Log "Database backup: $backup"

$args = @($RepairPy, '--db', $DbPath, '--collections-root', $CollectionsRoot)
if ($WhatIf) { $args += '--dry-run' }

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw 'Python is required for library repair.' }

& $py.Source @args
if ($LASTEXITCODE -ne 0) {
    Write-Log "Repair script failed with exit code $LASTEXITCODE"
    throw 'Library repair failed. Database backup preserved.'
}

Write-Log 'Repair script completed'

Start-JellyfinAfterRepair
Write-Log '=== Jellyfin library repair done ==='
Write-Log "Backup kept at: $backup"
