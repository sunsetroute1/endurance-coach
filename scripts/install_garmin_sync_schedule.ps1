# Register Garmin sync every 15 minutes (local time).
# -RecentDays 3 keeps each run to a short Garmin window. The pipeline still
# requests the normal 30-day window once per local day.
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "scheduled_task_helpers.ps1")

$TaskName = "EnduranceCoachGarminSync"
$SyncScript = Join-Path $PSScriptRoot "sync_garmin_pipeline.ps1"

if (-not (Test-Path $SyncScript)) {
    throw "Missing sync script: $SyncScript"
}

$action = New-SilentPowerShellTaskAction -ScriptPath $SyncScript -ScriptArgs @("-RecentDays", "3")
$repeatTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$startupTrigger.Delay = 'PT5M'
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logonTrigger.Delay = 'PT5M'
$triggers = @($repeatTrigger, $startupTrigger, $logonTrigger)
$settings = New-SilentScheduledTaskSettings -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$description = 'Garmin sync + process + analytics every 15 min (3-day window, 30-day once per day), plus 5 min after boot/logon (hidden)'

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal | Out-Null
    # Description is not updated by Set-ScheduledTask -Action/...; set explicitly.
    $existing = Get-ScheduledTask -TaskName $TaskName
    $existing.Description = $description
    $existing | Set-ScheduledTask | Out-Null
    Write-Host "Updated hidden '$TaskName' (every 15 min + AtStartup/AtLogon, 5 min delay)."
} else {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description $description | Out-Null
    Write-Host "Registered hidden '$TaskName' (every 15 min + AtStartup/AtLogon, 5 min delay)."
}

Set-ScheduledTaskHidden -TaskName $TaskName | Out-Null
Write-Host "Logs: $(Join-Path (Split-Path -Parent $PSScriptRoot) 'logs\sync-pipeline.log')"
Write-Host "Test now: powershell -WindowStyle Hidden -File `"$SyncScript`""
