# Register slskd to start automatically after reboot.
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "scheduled_task_helpers.ps1")

$TaskName = "Slskd"
$StartScript = Join-Path $PSScriptRoot "start_slskd_windows.ps1"

if (-not (Test-Path $StartScript)) {
    throw "Missing startup script: $StartScript"
}

$action = New-SilentPowerShellTaskAction -ScriptPath $StartScript
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT60S"
$settings = New-SilentScheduledTaskSettings -RestartCount 3
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Write-Host "Updated hidden scheduled task '$TaskName' (AtStartup, 60s delay)."
} else {
    try {
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            -Description "Start slskd Soulseek daemon after Windows boot (hidden)" | Out-Null
        Write-Host "Registered hidden scheduled task '$TaskName' (AtStartup, 60s delay)."
    } catch {
        Write-Warning "AtStartup registration failed; falling back to AtLogOn for current user."
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            -Description "Start slskd Soulseek daemon at user logon (hidden)" | Out-Null
        Write-Host "Registered hidden scheduled task '$TaskName' (AtLogOn)."
    }
}

Write-Host "To test now: powershell -WindowStyle Hidden -File `"$StartScript`""
