# Register Garmin sync pipeline at 9 AM, 12 PM, 6 PM, and 10 PM (local time).
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "scheduled_task_helpers.ps1")

$TaskName = "EnduranceCoachGarminSync"
$SyncScript = Join-Path $PSScriptRoot "sync_garmin_pipeline.ps1"

if (-not (Test-Path $SyncScript)) {
    throw "Missing sync script: $SyncScript"
}

$action = New-SilentPowerShellTaskAction -ScriptPath $SyncScript
$times = @("09:00", "12:00", "18:00", "22:00")
$triggers = foreach ($time in $times) {
    New-ScheduledTaskTrigger -Daily -At $time
}
$settings = New-SilentScheduledTaskSettings -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal | Out-Null
    Write-Host "Updated hidden '$TaskName' with daily triggers at: $($times -join ', ')"
} else {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description "Garmin sync + process + analytics at 9AM, 12PM, 6PM, 10PM (hidden)" | Out-Null
    Write-Host "Registered hidden '$TaskName' with daily triggers at: $($times -join ', ')"
}

Write-Host "Logs: $(Join-Path (Split-Path -Parent $PSScriptRoot) 'logs\sync-pipeline.log')"
Write-Host "Test now: powershell -WindowStyle Hidden -File `"$SyncScript`""
