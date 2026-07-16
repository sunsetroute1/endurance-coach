# Fallback safety scan every 30 minutes (catches missed watcher events).
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
. (Join-Path $RepoRoot "scripts\scheduled_task_helpers.ps1")

$TaskName = "MusicIngestFallbackScan"
$ScanScript = Join-Path $PSScriptRoot "run_beets_import.ps1"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-SilentPowerShellTaskAction -ScriptPath $ScanScript
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-SilentScheduledTaskSettings -RestartCount 3 -RestartInterval ([TimeSpan]::FromMinutes(5)) -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances "IgnoreNew"
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Fallback beets scan for Soulseek incoming music" | Out-Null

Set-ScheduledTaskHidden -TaskName $TaskName | Out-Null
Write-Host "Registered scheduled task '$TaskName' (every 30 minutes)."
