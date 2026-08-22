# Headless VPN/network watchdog: polls every 2 minutes, survives reboot/logon, auto-recovers stack.
param(
    [int]$IntervalMinutes = 2,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'scheduled_task_helpers.ps1')

$TaskName = 'VPN Network Watchdog'
$WatchdogScript = Join-Path $PSScriptRoot 'vpn_network_watchdog.ps1'
$LogDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'logs'
$LogFile = Join-Path $LogDir 'vpn-network-watchdog-task.log'

if (-not (Test-Path $WatchdogScript)) {
    throw "Missing watchdog script: $WatchdogScript"
}

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'."
    } else {
        Write-Host "Task '$TaskName' was not registered."
    }
    exit 0
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$wrapperScript = Join-Path $LogDir 'vpn-network-watchdog-wrapper.ps1'
$wrapperContent = @"
# Wrapper invoked by scheduled task; logs stdout and exit code.
`$ErrorActionPreference = 'Continue'
`$LogFile = '$($LogFile.Replace("'", "''"))'
`$Script = '$($WatchdogScript.Replace("'", "''"))'

function Write-TaskLog([string]`$Message) {
    `$line = "[`$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] `$Message"
    Add-Content -Path `$LogFile -Value `$line -Encoding UTF8
}

Write-TaskLog 'VPN network watchdog tick started'
try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File `$Script 2>&1 |
        ForEach-Object { Write-TaskLog `$_ }
    `$exit = `$LASTEXITCODE
    if (`$exit -ne 0) {
        Write-TaskLog "Watchdog exited with code `$exit" 'WARN'
    } else {
        Write-TaskLog 'VPN network watchdog tick complete'
    }
    exit `$exit
} catch {
    Write-TaskLog "Watchdog wrapper error: `$(`$_.Exception.Message)" 'ERR'
    exit 1
}
"@
Set-Content -Path $wrapperScript -Value $wrapperContent -Encoding UTF8

$action = New-SilentPowerShellTaskAction -ScriptPath $wrapperScript
$triggers = @(
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)),
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME),
    (New-ScheduledTaskTrigger -AtStartup)
)
$settings = New-SilentScheduledTaskSettings `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 8) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances 'IgnoreNew'
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal | Out-Null
    Write-Host "Updated '$TaskName' (every $IntervalMinutes min, at logon, at startup)."
} else {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $triggers `
        -Settings $settings `
        -Principal $principal `
        -Description 'Headless VPN/network transition detection and media stack recovery (every 2 min)' | Out-Null
    Write-Host "Registered '$TaskName' (every $IntervalMinutes min, at logon, at startup)."
}

Set-ScheduledTaskHidden -TaskName $TaskName | Out-Null

# Run once immediately so state is initialized after install.
Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null

Write-Host "Task log: $LogFile"
Write-Host "Recovery log: C:\ProgramData\mediapc-stack\vpn-network-recovery.log"
