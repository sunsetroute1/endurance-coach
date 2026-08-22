# Lean out Windows consumer bloat; keep media stack functionality intact.
param(
    [switch]$WhatIf
)

$ErrorActionPreference = 'Continue'

function Test-IsAdministrator {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Write-Step([string]$Message) {
    Write-Host "[leanout] $Message"
}

function Remove-RunKeyValue {
    param([string]$Path, [string]$Name)
    if (-not (Test-Path $Path)) { return }
    $existing = Get-ItemProperty -Path $Path -Name $Name -ErrorAction SilentlyContinue
    if (-not $existing) { return }
    if ($WhatIf) {
        Write-Step "Would remove Run key: $Path\$Name"
        return
    }
    Remove-ItemProperty -Path $Path -Name $Name -ErrorAction SilentlyContinue
    Write-Step "Removed Run key: $Name"
}

function Disable-ScheduledTaskSafe {
    param([string]$TaskName)
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) { return }
    if ($task.State -eq 'Disabled') { return }
    if ($WhatIf) {
        Write-Step "Would disable task: $TaskName"
        return
    }
    Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
    Write-Step "Disabled task: $TaskName"
}

function Disable-ServiceSafe {
    param([string]$Name)
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if (-not $svc) { return }
    if ($svc.StartType -eq 'Disabled') { return }
    if ($WhatIf) {
        Write-Step "Would disable service: $Name"
        return
    }
    if ($svc.Status -eq 'Running') {
        Stop-Service -Name $Name -Force -ErrorAction SilentlyContinue
    }
    Set-Service -Name $Name -StartupType Disabled -ErrorAction SilentlyContinue
    Write-Step "Disabled service: $Name"
}

function Set-RegistryDword {
    param([string]$Path, [string]$Name, [int]$Value)
    if ($WhatIf) {
        Write-Step "Would set $Path\$Name = $Value"
        return
    }
    try {
        if (-not (Test-Path $Path)) {
            New-Item -Path $Path -Force | Out-Null
        }
        Set-ItemProperty -Path $Path -Name $Name -Value $Value -Type DWord -Force -ErrorAction Stop
        Write-Step "Set $Name = $Value"
    } catch {
        Write-Step "Skipped $Name (protected or unavailable): $($_.Exception.Message)"
    }
}

if (-not (Test-IsAdministrator)) {
    throw 'Run elevated: server lean-out requires administrator privileges.'
}

Write-Host '=== Media Server Lean-Out ===' -ForegroundColor Cyan

# --- Consumer UI / Copilot / Widgets / Game Bar ---
$userHive = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced'
Set-RegistryDword -Path $userHive -Name 'ShowCopilotButton' -Value 0
Set-RegistryDword -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced' -Name 'TaskbarDa' -Value 0
Set-RegistryDword -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\GameDVR' -Name 'AppCaptureEnabled' -Value 0
Set-RegistryDword -Path 'HKCU:\System\GameConfigStore' -Name 'GameDVR_Enabled' -Value 0
Set-RegistryDword -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsCopilot' -Name 'TurnOffWindowsCopilot' -Value 1
Set-RegistryDword -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Dsh' -Name 'AllowNewsAndInterests' -Value 0
Set-RegistryDword -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects' -Name 'VisualFXSetting' -Value 2

# --- Telemetry / delivery optimization / consumer services ---
$disableServices = @(
    'DiagTrack',
    'DoSvc',
    'WpnService',
    'WSAIFabricSvc',
    'whesvc',
    'AUEPLauncher',
    'IntelCollectorService',
    'IntelTelemetryAgent',
    'SystemUsageReportSvc_QUEENCREEK',
    'DSAService',
    'DSAUpdateService',
    'PresentMonSharedService',
    'MediaIngestionService',
    'bthserv',
    'BTAGService',
    'BthAvctpSvc',
    'lfsvc',
    'StiSvc',
    'SysMain',
    'PcaSvc',
    'Spooler'
)
foreach ($svc in $disableServices) {
    Disable-ServiceSafe -Name $svc
}

# Keep IntelGraphicsSoftwareService for Jellyfin QSV transcode.
Disable-ServiceSafe -Name 'WidgetService'

# --- Startup Run keys (junk) ---
$userRun = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$machineRun = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run'
foreach ($name in @('OneDrive', 'GoogleDriveFS', 'Unified Remote V3')) {
    Remove-RunKeyValue -Path $userRun -Name $name
}
Remove-RunKeyValue -Path $machineRun -Name 'SunJavaUpdateSched'

# --- Startup folder junk ---
$startupFolder = [Environment]::GetFolderPath('Startup')
$sonarrLnk = Join-Path $startupFolder 'Sonarr.lnk'
if (Test-Path $sonarrLnk) {
    if ($WhatIf) {
        Write-Step "Would remove $sonarrLnk"
    } else {
        Remove-Item $sonarrLnk -Force
        Write-Step 'Removed stale Sonarr startup shortcut'
    }
}

$commonStartup = 'C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup'
$rustDeskTray = Join-Path $commonStartup 'RustDesk Tray.lnk'
if (Test-Path $rustDeskTray) {
    if ($WhatIf) {
        Write-Step "Would remove $rustDeskTray"
    } else {
        Remove-Item $rustDeskTray -Force
        Write-Step 'Removed RustDesk tray startup (service still runs)'
    }
}

# --- Scheduled task bloat ---
$disableTasks = @(
    'OneDrive Reporting Task-S-1-5-21-3337704602-430710009-2244514119-1000',
    'OneDrive Standalone Update Task-S-1-5-21-3337704602-430710009-2244514119-1000',
    'OneDrive Startup Task-S-1-5-21-3337704602-430710009-2244514119-1000',
    'AMDAutoUpdate',
    'AMDInstallLauncher',
    'AMDLinkUpdate',
    'AMDRyzenMasterSDKTask',
    'StartAUEP',
    'StartCN',
    'StartCNBM',
    'StartDVR',
    'ModifyLinkUpdate',
    'USER_ESRV_SVC_QUEENCREEK',
    'MicrosoftEdgeUpdateTaskMachineCore{D35B0E48-AD13-4996-81E5-071FF39F873E}',
    'MicrosoftEdgeUpdateTaskMachineUA{2519F488-4C04-4B48-9937-85003F96B403}',
    'GoogleUpdaterTaskSystem152.0.7933.0{E891E93D-5023-4618-B483-8583A595648B}',
    'BraveSoftwareUpdateTaskMachineCore{748C70F7-6FDD-4D14-8F61-CFD8C3565654}',
    'BraveSoftwareUpdateTaskMachineUA{3A7C3DFA-778A-4588-8395-9A33125E831B}'
)
foreach ($task in $disableTasks) {
    Disable-ScheduledTaskSafe -TaskName $task
}

# --- Redundant native stack tasks (Docker owns these) ---
$coachHelpers = Join-Path $PSScriptRoot 'coach-stack-helpers.ps1'
$coachDocker = $false
if (Test-Path $coachHelpers) {
    . $coachHelpers
    $coachDocker = Test-CoachDockerMode
}
if ($coachDocker) {
    foreach ($task in @('EnduranceCoachAPI', 'EnduranceCoachMCP', 'Slskd')) {
        Disable-ScheduledTaskSafe -TaskName $task
    }
    Write-Step 'Disabled native coach/slskd tasks (Docker mode active)'
}

$disableSonarr = 'C:\ProgramData\docker\media-stack\scripts\disable-native-sonarr.ps1'
if (Test-Path $disableSonarr) {
    if ($WhatIf) {
        Write-Step 'Would run disable-native-sonarr.ps1'
    } else {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $disableSonarr 2>&1 | ForEach-Object { Write-Step $_ }
    }
}

# --- Stop consumer processes if running ---
if (-not $WhatIf) {
    foreach ($proc in @('Widgets', 'WidgetService', 'PhoneExperienceHost', 'CrossDeviceResume', 'OneDrive', 'GoogleDriveFS')) {
        Get-Process -Name $proc -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

# --- Re-apply server hardening ---
$powerScript = Join-Path $PSScriptRoot 'configure_power_outage_hardening.ps1'
if ((Test-Path $powerScript) -and -not $WhatIf) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $powerScript | Out-Null
    Write-Step 'Re-applied power-outage hardening'
}

Write-Host ''
Write-Host 'Lean-out complete. Kept: Jellyfin, Docker, ExpressVPN, Caddy, Tautulli, TightVNC, RustDesk, media stack tasks.' -ForegroundColor Green
Write-Host 'Run: .\scripts\get_server_wellness.ps1'
