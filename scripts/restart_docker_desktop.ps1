$ErrorActionPreference = 'Continue'

Write-Host 'WSL shutdown...'
wsl --shutdown
Start-Sleep -Seconds 8

Write-Host 'Stopping Docker...'
Stop-Process -Name 'Docker Desktop', 'com.docker.backend', 'docker' -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 5

Write-Host 'Starting Docker Desktop...'
Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe' -ArgumentList '-Autostart' -WindowStyle Hidden

$deadline = (Get-Date).AddMinutes(3)
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
        Write-Host 'Docker ready'
        & docker ps --format '{{.Names}}: {{.Status}}'
        exit 0
    }
    try { if (-not $proc.HasExited) { $proc.Kill() } } catch {}
    Start-Sleep -Seconds 10
}

Write-Host 'Docker not ready after 3 minutes'
exit 1
