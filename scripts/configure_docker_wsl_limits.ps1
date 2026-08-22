# Cap WSL2/Docker resource use to reduce Hyper-V crashes on the media server.
param(
    [int]$MemoryGB = 6,
    [int]$Processors = 4,
    [switch]$ApplyNow
)

$ErrorActionPreference = 'Stop'

$wslConfigPath = Join-Path $env:USERPROFILE '.wslconfig'
$content = @"
[wsl2]
memory=${MemoryGB}GB
processors=$Processors
swap=2GB
localhostForwarding=true
"@

Set-Content -Path $wslConfigPath -Value $content -Encoding ASCII
Write-Host "Wrote $wslConfigPath (${MemoryGB}GB RAM, $Processors CPUs)"

try {
    wsl --update 2>&1 | ForEach-Object { Write-Host $_ }
} catch {
    Write-Warning "wsl --update failed: $($_.Exception.Message)"
}

if ($ApplyNow) {
    Write-Host 'Shutting down WSL to apply new limits (Docker will restart)...'
    wsl --shutdown
    Start-Sleep -Seconds 8
    $bootScript = 'C:\ProgramData\docker\media-stack\scripts\boot-start-media-stack.ps1'
    if (Test-Path $bootScript) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootScript
    }
    Write-Host 'WSL limits applied.'
} else {
    Write-Host 'Limits take effect after the next WSL restart (wsl --shutdown or reboot).'
    Write-Host 'Re-run with -ApplyNow to apply immediately.'
}
