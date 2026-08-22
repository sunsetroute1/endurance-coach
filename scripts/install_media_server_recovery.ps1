# Install/repair unattended media-server recovery: auto-login, power hardening, boot tasks.
param(
    [SecureString]$AutoLoginPassword,
    [switch]$SkipAutoLogin,
    [switch]$SkipPowerHardening,
    [switch]$SkipDockerAutoStart
)

$ErrorActionPreference = 'Stop'
$ScriptsDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptsDir

function Test-IsAdministrator {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Invoke-Step {
    param(
        [string]$Title,
        [string]$ScriptPath,
        [hashtable]$Arguments = @{}
    )
    if (-not (Test-Path $ScriptPath)) {
        throw "Missing script: $ScriptPath"
    }
    Write-Host ""
    Write-Host "==> $Title" -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ScriptPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Title failed with exit code $LASTEXITCODE"
    }
}

Write-Host 'Media server recovery installer' -ForegroundColor Cyan
Write-Host "User: $env:USERNAME  Computer: $env:COMPUTERNAME"
Write-Host ''

. (Join-Path $ScriptsDir 'scheduled_task_helpers.ps1')

# 1. Re-register endurance-coach + music tasks (includes VPN watchdog + media stack boot).
Invoke-Step -Title 'Register endurance-coach scheduled tasks' `
    -ScriptPath (Join-Path $ScriptsDir 'install_all_services.ps1')

# 2. Watchboard with AtLogOn + AtStartup.
$watchboardInstaller = 'C:\Users\adminnie\Projects\automation-watchboard\installer\Install-AutomationWatchboard.ps1'
if (Test-Path $watchboardInstaller) {
    Invoke-Step -Title 'Register Automation Watchboard boot task' -ScriptPath $watchboardInstaller
} else {
    Write-Warning "Watchboard installer not found: $watchboardInstaller"
}

# 3. Post-boot safety net (4 min after boot/logon, after Docker Desktop has time to start).
$postBootScript = Join-Path $ScriptsDir 'post_boot_stack_recovery.ps1'
$postBootAction = New-SilentPowerShellTaskAction -ScriptPath $postBootScript
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$startupTrigger.Delay = 'PT4M'
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$logonTrigger.Delay = 'PT4M'
$postBootSettings = New-SilentScheduledTaskSettings `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -MultipleInstances 'IgnoreNew'
$postBootPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$postBootTask = 'Media Server Post-Boot Recovery'
$existingPostBoot = Get-ScheduledTask -TaskName $postBootTask -ErrorAction SilentlyContinue
if ($existingPostBoot) {
    Set-ScheduledTask -TaskName $postBootTask -Action $postBootAction -Trigger @($startupTrigger, $logonTrigger) `
        -Settings $postBootSettings -Principal $postBootPrincipal | Out-Null
    Write-Host "Updated scheduled task: $postBootTask"
} else {
    Register-ScheduledTask -TaskName $postBootTask -Action $postBootAction -Trigger @($startupTrigger, $logonTrigger) `
        -Settings $postBootSettings -Principal $postBootPrincipal `
        -Description 'One-shot Docker/media stack recovery 4 min after boot or auto-login' | Out-Null
    Write-Host "Registered scheduled task: $postBootTask"
}
Set-ScheduledTaskHidden -TaskName $postBootTask | Out-Null

# 4. FanControl + LibreHardwareMonitor: add AtStartup alongside AtLogOn.
$logonBootTasks = @(
    @{
        Name = 'FanControl'
        Script = 'C:\ProgramData\mediapc-stack\scripts\ensure-fancontrol.ps1'
    },
    @{
        Name = 'LibreHardwareMonitor'
        Script = 'C:\Users\adminnie\Projects\automation-watchboard\scripts\ensure_hardware_sensors.ps1'
    }
)
foreach ($entry in $logonBootTasks) {
    if (-not (Test-Path $entry.Script)) {
        Write-Warning "Skipping $($entry.Name): missing $($entry.Script)"
        continue
    }
    Write-Host "Refreshing $($entry.Name) task (AtLogOn + AtStartup)..."
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $entry.Script | Out-Null
    $task = Get-ScheduledTask -TaskName $entry.Name -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Warning "Task not found after install: $($entry.Name)"
        continue
    }
    $startup = New-ScheduledTaskTrigger -AtStartup
    $startup.Delay = 'PT2M'
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    Set-ScheduledTask -TaskName $entry.Name -Trigger @($logon, $startup) | Out-Null
    Write-Host "  $($entry.Name): AtLogOn + AtStartup (2 min delay)"
}

# 5. Docker auto-start (user session).
if (-not $SkipDockerAutoStart) {
    Invoke-Step -Title 'Enable Docker Desktop auto-start' `
        -ScriptPath (Join-Path $ScriptsDir 'enable_docker_autostart.ps1')
}

# 6. Power hardening (admin).
if (-not $SkipPowerHardening) {
    if (Test-IsAdministrator) {
        Invoke-Step -Title 'Apply power-outage hardening' `
            -ScriptPath (Join-Path $ScriptsDir 'configure_power_outage_hardening.ps1')
    } else {
        Write-Warning 'Skipped power hardening (run elevated to apply).'
    }
}

# 7. Auto-login (admin + password).
if (-not $SkipAutoLogin) {
    if (-not (Test-IsAdministrator)) {
        Write-Warning 'Skipped auto-login (run elevated with -AutoLoginPassword).'
    } elseif (-not $AutoLoginPassword) {
        Write-Warning 'Skipped auto-login (pass -AutoLoginPassword or run configure_media_server_autologin.ps1 separately).'
    } else {
        $autoLoginScript = Join-Path $ScriptsDir 'configure_media_server_autologin.ps1'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $autoLoginScript `
            -Username $env:USERNAME -Password $AutoLoginPassword
        if ($LASTEXITCODE -ne 0) {
            throw 'Auto-login configuration failed'
        }
    }
}

Write-Host ''
Write-Host '=== Verification ===' -ForegroundColor Cyan
$expectedTasks = @(
    'Media Stack Boot',
    'Media Server Post-Boot Recovery',
    'VPN Network Watchdog',
    'EnduranceCoachWatchdog',
    'AutomationWatchboard',
    'MusicIngestWatcher',
    'Caddy Server',
    'DuckDNS Updater'
)
foreach ($name in $expectedTasks) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host ("  {0,-32} MISSING" -f $name) -ForegroundColor Yellow
        continue
    }
    $triggers = ($task.Triggers | ForEach-Object { $_.CimClass.CimClassName -replace 'MSFT_Task', '' }) -join ', '
    Write-Host ("  {0,-32} {1}" -f $name, $triggers)
}

$dockerSettings = Join-Path $env:APPDATA 'Docker\settings-store.json'
if (Test-Path $dockerSettings) {
    $autoStart = (Get-Content $dockerSettings -Raw | ConvertFrom-Json).AutoStart
    Write-Host ("  Docker AutoStart                 {0}" -f $autoStart)
}

$autoLogon = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' `
    -Name AutoAdminLogon -ErrorAction SilentlyContinue).AutoAdminLogon
Write-Host ("  Windows AutoAdminLogon           {0}" -f $(if ($autoLogon -eq '1') { 'enabled' } else { 'NOT SET (run configure_media_server_autologin.ps1)' }))

Write-Host ''
Write-Host 'Media server recovery installer complete.' -ForegroundColor Green
if ($autoLogon -ne '1') {
    Write-Host ''
    Write-Host 'To finish auto-login (required for unattended boot), run elevated:' -ForegroundColor Yellow
    Write-Host '  .\scripts\configure_media_server_autologin.ps1'
}
