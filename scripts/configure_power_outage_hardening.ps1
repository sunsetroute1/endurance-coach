# Harden Windows for monsoon / weak-grid power outages on an always-on media server.
param(
    [switch]$RevertFastStartup
)

$ErrorActionPreference = 'Stop'

function Test-IsAdministrator {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

if (-not (Test-IsAdministrator)) {
    throw 'Run elevated: power and boot hardening require administrator privileges.'
}

Write-Host 'Applying power-outage hardening...' -ForegroundColor Cyan

# High performance plan keeps CPU/network responsive during recovery.
$highPerf = '8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c'
powercfg /setactive $highPerf | Out-Null
Write-Host '  Power plan: High performance'

# Never sleep or hibernate on AC (server stays awake for watchdogs).
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null
powercfg /change monitor-timeout-ac 0 | Out-Null
powercfg /change disk-timeout-ac 0 | Out-Null
powercfg /hibernate off | Out-Null
Write-Host '  Sleep/hibernate: disabled on AC'

# Fast Startup can leave Docker/WSL in a bad state after unclean power loss.
$powerKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power'
if (-not (Test-Path $powerKey)) {
    New-Item -Path $powerKey -Force | Out-Null
}
if ($RevertFastStartup) {
    Set-ItemProperty -Path $powerKey -Name 'HiberbootEnabled' -Value 1 -Type DWord
    Write-Host '  Fast Startup: re-enabled'
} else {
    Set-ItemProperty -Path $powerKey -Name 'HiberbootEnabled' -Value 0 -Type DWord
    Write-Host '  Fast Startup: disabled (cleaner recovery after power loss)'
}

# Reduce surprise reboots from Windows Update during unstable power (notify only).
$auKey = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
if (-not (Test-Path $auKey)) {
    New-Item -Path $auKey -Force | Out-Null
}
Set-ItemProperty -Path $auKey -Name 'NoAutoRebootWithLoggedOnUsers' -Value 1 -Type DWord
Set-ItemProperty -Path $auKey -Name 'AUOptions' -Value 3 -Type DWord
Write-Host '  Windows Update: notify before download/install; no auto-reboot while logged on'

# Keep network adapters from power-saving during recovery.
Get-NetAdapter -Physical -ErrorAction SilentlyContinue | ForEach-Object {
    try {
        Disable-NetAdapterPowerManagement -Name $_.Name -ArpOffload Disabled -NSOffload Disabled `
            -RSCEnabled Disabled -ErrorAction SilentlyContinue | Out-Null
        Set-NetAdapterAdvancedProperty -Name $_.Name -DisplayName 'Energy Efficient Ethernet' `
            -DisplayValue 'Disabled' -ErrorAction SilentlyContinue | Out-Null
    } catch {
        # Adapter-specific properties vary; non-fatal.
    }
}
Write-Host '  Network adapters: power-saving features reduced where supported'

Write-Host ''
Write-Host 'Power-outage hardening applied.' -ForegroundColor Green
Write-Host 'Pair with BIOS "power on after AC loss" and a UPS when available.'
