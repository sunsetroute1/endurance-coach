# Register endurance-coach MCP server to start automatically after reboot.
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "scheduled_task_helpers.ps1")

$TaskName = "EnduranceCoachMCP"
$StartScript = Join-Path $PSScriptRoot "start_mcp_windows.ps1"

if (-not (Test-Path $StartScript)) {
    throw "Missing startup script: $StartScript"
}

$action = New-SilentPowerShellTaskAction -ScriptPath $StartScript
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT45S"
$settings = New-SilentScheduledTaskSettings -RestartCount 3
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    Write-Host "Updated hidden scheduled task '$TaskName' (AtStartup, 45s delay)."
} else {
    try {
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            -Description "Start endurance-coach MCP HTTP server after Windows boot (hidden)" | Out-Null
        Write-Host "Registered hidden scheduled task '$TaskName' (AtStartup, 45s delay)."
    } catch {
        Write-Warning "AtStartup registration failed; falling back to AtLogOn for current user."
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            -Description "Start endurance-coach MCP HTTP server at user logon (hidden)" | Out-Null
        Write-Host "Registered hidden scheduled task '$TaskName' (AtLogOn)."
    }
}

Write-Host "To test now: powershell -WindowStyle Hidden -File `"$StartScript`""
