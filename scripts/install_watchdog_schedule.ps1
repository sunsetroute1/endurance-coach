# Run service watchdog every 5 minutes (reboot, VPN, and crash recovery).
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "scheduled_task_helpers.ps1")

$TaskName = "EnduranceCoachWatchdog"
$WatchdogScript = Join-Path $PSScriptRoot "watchdog_services.ps1"

if (-not (Test-Path $WatchdogScript)) {
    throw "Missing watchdog script: $WatchdogScript"
}

$action = New-SilentPowerShellTaskAction -ScriptPath $WatchdogScript
$triggers = @(
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)),
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME),
    (New-ScheduledTaskTrigger -AtStartup)
)
$settings = New-SilentScheduledTaskSettings -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal | Out-Null
    Write-Host "Updated hidden '$TaskName' (every 5 min, at logon, at startup)."
} else {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description "Ensure endurance-coach API/MCP stay up; recover after VPN/network changes (hidden)" | Out-Null
    Write-Host "Registered hidden '$TaskName' (every 5 min, at logon, at startup)."
}

Write-Host "Logs: $(Join-Path (Split-Path -Parent $PSScriptRoot) 'logs\watchdog.log')"
