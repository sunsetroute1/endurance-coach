# Register music ingest watcher to start at boot.
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
. (Join-Path $RepoRoot "scripts\scheduled_task_helpers.ps1")

$TaskName = "MusicIngestWatcher"
$StartScript = Join-Path $PSScriptRoot "start_music_watcher.ps1"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-SilentPowerShellTaskAction -ScriptPath $StartScript
$triggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
)
$triggers[0].Delay = "PT90S"
$settings = New-SilentScheduledTaskSettings -RestartCount 999 -RestartInterval ([TimeSpan]::FromMinutes(1)) -MultipleInstances "IgnoreNew"
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "Watch Soulseek incoming folder and import with beets" | Out-Null

Set-ScheduledTaskHidden -TaskName $TaskName | Out-Null
Write-Host "Registered scheduled task '$TaskName' (AtStartup, 90s delay)."
