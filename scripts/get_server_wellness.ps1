# Quick wellness snapshot for the media server.
param(
    [switch]$Json
)

$ErrorActionPreference = 'SilentlyContinue'

function Test-Port([int]$Port, [string]$HostName = '127.0.0.1') {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $a = $c.BeginConnect($HostName, $Port, $null, $null)
        if ($a.AsyncWaitHandle.WaitOne(800) -and $c.Connected) { $c.Close(); return $true }
        $c.Close(); return $false
    } catch { return $false }
}

function Get-PreferredLanIp {
    $privatePattern = '^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)'
    $vpnPatterns = @('wireguard', 'openvpn', 'tap', 'tun', 'wintun', 'express', 'vpn', 'wsl', 'hyper-v', 'vethernet', 'docker', 'loopback')
    foreach ($addr in (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -match $privatePattern -and $_.IPAddress -notmatch '^127\.' })) {
        $adapter = Get-NetAdapter -InterfaceIndex $addr.InterfaceIndex -ErrorAction SilentlyContinue
        if (-not $adapter -or $adapter.Status -ne 'Up') { continue }
        $name = $adapter.Name.ToLower()
        $isVpn = $false
        foreach ($pattern in $vpnPatterns) {
            if ($name -like "*$pattern*") { $isVpn = $true; break }
        }
        if (-not $isVpn) { return $addr.IPAddress }
    }
    return $null
}

$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$uptime = (Get-Date) - $boot
$autoLogon = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' -Name AutoAdminLogon).AutoAdminLogon

docker info 2>$null | Out-Null
$dockerOk = ($LASTEXITCODE -eq 0)
$lanIp = Get-PreferredLanIp
$caddyHost = if ($lanIp) { $lanIp } else { '127.0.0.1' }

$checks = [ordered]@{
    uptime_hours          = [math]::Round($uptime.TotalHours, 1)
    auto_login            = ($autoLogon -eq '1')
    jellyfin_8096         = Test-Port 8096
    caddy_443             = Test-Port 443 -HostName $caddyHost
    docker_daemon         = $dockerOk
    expressvpn_service    = ((Get-Service ExpressVpnService).Status -eq 'Running')
    coach_api_8000        = Test-Port 8000
    coach_postgres_5432   = Test-Port 5432
    sonarr_8989           = Test-Port 8989
    radarr_7878           = Test-Port 7878
    prowlarr_9696         = Test-Port 9696
    navidrome_4533        = Test-Port 4533
    slskd_5030            = Test-Port 5030
}

$containers = @(docker ps --format '{{.Names}}' 2>$null)
$checks.container_count = $containers.Count
$checks.containers = ($containers -join ', ')

if ($Json) {
    $checks | ConvertTo-Json
    exit 0
}

Write-Host '=== Media Server Wellness ===' -ForegroundColor Cyan
Write-Host ("Uptime: {0:0.#} hours (since {1:yyyy-MM-dd HH:mm})" -f $checks.uptime_hours, $boot)
Write-Host ("Auto-login: {0}" -f $(if ($checks.auto_login) { 'enabled' } else { 'DISABLED' }))
Write-Host ''
Write-Host 'Core services:' -ForegroundColor Cyan
foreach ($key in @('jellyfin_8096','caddy_443','docker_daemon','expressvpn_service','coach_api_8000','coach_postgres_5432')) {
    $ok = $checks[$key]
    $label = ($key -replace '_', ' ')
    Write-Host ("  {0,-22} {1}" -f $label, $(if ($ok) { 'OK' } else { 'FAIL' }))
}
Write-Host ''
Write-Host 'Media stack ports:' -ForegroundColor Cyan
foreach ($key in @('sonarr_8989','radarr_7878','prowlarr_9696','navidrome_4533','slskd_5030')) {
    $ok = $checks[$key]
    $label = ($key -replace '_', ' ')
    Write-Host ("  {0,-22} {1}" -f $label, $(if ($ok) { 'OK' } else { 'FAIL' }))
}
Write-Host ''
Write-Host ("Docker containers running: {0}" -f $checks.container_count)
$failed = @($checks.Keys | Where-Object { $_ -match '^(jellyfin|caddy|docker|expressvpn|coach|sonarr|radarr|prowlarr|navidrome|slskd)_' -and -not $checks[$_] })
if ($failed.Count -gt 0) {
    Write-Host ''
    Write-Host ("Issues: {0}" -f ($failed -join ', ')) -ForegroundColor Yellow
    exit 1
}
Write-Host ''
Write-Host 'All checks passed.' -ForegroundColor Green
exit 0
