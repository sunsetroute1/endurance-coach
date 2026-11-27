# Run AFTER enabling SVM/virtualization in BIOS and rebooting.
# Verifies firmware virtualization, starts WSL + Docker, then recovers the media/coach stacks.
$ErrorActionPreference = 'Continue'

function Write-Step([string]$Message) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $Message"
}

Write-Step 'Checking firmware virtualization (SVM)...'
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
if (-not $cpu.VirtualizationFirmwareEnabled) {
    Write-Host ''
    Write-Host 'BLOCKED: Virtualization is still disabled in BIOS.' -ForegroundColor Red
    Write-Host 'Enable SVM Mode, save, reboot, then run this script again.'
    Write-Host ''
    Write-Host 'Gigabyte B450 path: BIOS -> Advanced -> CPU Configuration -> SVM Mode -> Enabled'
    exit 1
}

Write-Step "SVM enabled on $($cpu.Name)"

Write-Step 'Checking WSL features...'
$vmp = (Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -ErrorAction SilentlyContinue).State
$wsl = (Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -ErrorAction SilentlyContinue).State
if ($vmp -ne 'Enabled' -or $wsl -ne 'Enabled') {
    Write-Host 'WARN: WSL/Virtual Machine Platform not fully enabled. Docker may still fail.' -ForegroundColor Yellow
}

Write-Step 'Starting WSL...'
wsl --shutdown 2>$null | Out-Null
Start-Sleep -Seconds 3
wsl -d docker-desktop -e /bin/true 2>$null | Out-Null
Start-Sleep -Seconds 5

Write-Step 'Restarting Docker Desktop...'
Stop-Process -Name 'Docker Desktop', 'com.docker.backend', 'docker' -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5
$dockerDesktop = Join-Path ${env:ProgramFiles} 'Docker\Docker\Docker Desktop.exe'
if (-not (Test-Path $dockerDesktop)) {
    Write-Host "ERROR: Docker Desktop not found at $dockerDesktop" -ForegroundColor Red
    exit 1
}
Start-Process -FilePath $dockerDesktop -ArgumentList '-Autostart' -WindowStyle Hidden

$deadline = (Get-Date).AddMinutes(4)
Write-Step 'Waiting for Docker daemon...'
while ((Get-Date) -lt $deadline) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'docker'
    $psi.Arguments = 'info'
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    if ($proc.WaitForExit(8000) -and $proc.ExitCode -eq 0) {
        Write-Step 'Docker daemon ready'
        break
    }
    try { if (-not $proc.HasExited) { $proc.Kill() } } catch {}
    Start-Sleep -Seconds 10
}

if ($proc.ExitCode -ne 0) {
    Write-Host 'ERROR: Docker did not become ready within 4 minutes.' -ForegroundColor Red
    exit 1
}

& docker ps --format '{{.Names}}: {{.Status}}'

$watchdog = Join-Path $PSScriptRoot 'vpn_network_watchdog.ps1'
if (Test-Path $watchdog) {
    Write-Step 'Running stack recovery...'
    & $watchdog -ForceRecovery
}

Write-Step 'Done. Check Watchboard or run: docker ps'
