# Create desktop shortcuts for manual Garmin -> MCP sync.
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Desktop = [Environment]::GetFolderPath("Desktop")
$ManualSync = Join-Path $PSScriptRoot "sync_garmin_manual.ps1"
$PipelineSync = Join-Path $PSScriptRoot "sync_garmin_pipeline.ps1"

function New-DesktopShortcut {
    param(
        [string]$Name,
        [string]$ScriptPath,
        [string[]]$ExtraArgs = @(),
        [switch]$Silent
    )

    $lnkPath = Join-Path $Desktop "$Name.lnk"
    $argString = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass"
    )
    if (-not $Silent) {
        $argString += "-NoExit"
    } else {
        $argString += "-WindowStyle", "Hidden"
    }
    $argString += @("-File", "`"$ScriptPath`"") + $ExtraArgs
    $arguments = $argString -join " "

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($lnkPath)
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $ProjectRoot
    if ($Silent) {
        $shortcut.WindowStyle = 7
    } else {
        $shortcut.WindowStyle = 1
    }
    $shortcut.Description = "Endurance Coach: $Name"
    $shortcut.Save()

    Write-Host "Created $lnkPath"
}

if (-not (Test-Path $ManualSync)) {
    throw "Missing script: $ManualSync"
}

New-DesktopShortcut -Name "Sync Garmin to MCP" -ScriptPath $ManualSync
New-DesktopShortcut -Name "Sync Garmin Activities" -ScriptPath $ManualSync -ExtraArgs @("-ActivitiesOnly")
New-DesktopShortcut -Name "Sync Garmin Full Pipeline" -ScriptPath $PipelineSync
New-DesktopShortcut -Name "Fix Endurance Services" -ScriptPath (Join-Path $PSScriptRoot "fix_endurance_services.ps1")
New-DesktopShortcut -Name "Update Tools Suite" -ScriptPath (Join-Path $PSScriptRoot "update_tools_suite.ps1") -Silent

Write-Host ""
Write-Host "Desktop shortcuts ready."
