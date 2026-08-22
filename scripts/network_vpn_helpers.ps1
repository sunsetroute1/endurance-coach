# Shared VPN / network transition detection and recovery for local automations.
$ErrorActionPreference = 'Continue'

$script:StateFile = 'C:\ProgramData\mediapc-stack\vpn-network-state.json'
$script:VpnRecoveryLog = 'C:\ProgramData\mediapc-stack\vpn-network-recovery.log'
$script:RecoveryCooldownFile = 'C:\ProgramData\mediapc-stack\vpn-network-last-recovery.json'
$script:DockerRestartCooldownFile = 'C:\ProgramData\mediapc-stack\vpn-network-last-docker-restart.json'
$script:RecoveryCooldownMinutes = 15
$script:DockerRestartCooldownMinutes = 30
$script:PostBootGraceMinutes = 25
$script:DockerStackHelpersPath = 'C:\ProgramData\docker\media-stack\scripts\docker-stack-helpers.ps1'
$script:NativeDecommissionedMarker = 'C:\ProgramData\docker\media-stack\native-decommissioned.marker'
$script:DockerStackHelpersImported = $false
$script:LanRoutePrefixes = @('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')

# Dot-source docker helpers at script scope so recovery functions are visible everywhere.
$savedVpnLogInit = $script:VpnRecoveryLog
$savedStateFileInit = $script:StateFile
if (Test-Path $script:DockerStackHelpersPath) {
    . $script:DockerStackHelpersPath
    $script:DockerStackHelpersImported = $true
}
$script:VpnRecoveryLog = $savedVpnLogInit
$script:StateFile = $savedStateFileInit

function Write-VpnLog {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [$Level] $Message"
    Add-Content -Path $script:VpnRecoveryLog -Value $line -Encoding UTF8
}

function Get-WanAdapterName {
    $candidates = @(
        (Join-Path (Split-Path $PSScriptRoot -Parent) 'installer\local.json'),
        'C:\Users\adminnie\Projects\endurance-coach\installer\local.json'
    )
    foreach ($path in $candidates) {
        if (-not (Test-Path $path)) { continue }
        try {
            $json = Get-Content $path -Raw | ConvertFrom-Json
            if ($json.wan_adapter_name) { return [string]$json.wan_adapter_name }
        } catch {}
    }
    return 'Ethernet'
}

function Get-PreferredLanIp {
    $vpnPatterns = @(
        'wireguard', 'openvpn', 'tap', 'tun', 'wintun', 'nord', 'express',
        'proton', 'zerotier', 'tailscale', 'hamachi', 'vpn', 'virtual', 'lightway',
        'wsl', 'hyper-v', 'vethernet', 'docker', 'loopback'
    )
    $privatePattern = '^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)'

    $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -match $privatePattern -and $_.IPAddress -notmatch '^127\.' }

    foreach ($addr in $addresses) {
        $adapter = Get-NetAdapter -InterfaceIndex $addr.InterfaceIndex -ErrorAction SilentlyContinue
        if (-not $adapter -or $adapter.Status -ne 'Up') { continue }
        $name = $adapter.Name.ToLower()
        $isVpn = $false
        foreach ($pattern in $vpnPatterns) {
            if ($name -like "*$pattern*" -or $adapter.InterfaceDescription.ToLower() -like "*$pattern*") {
                $isVpn = $true
                break
            }
        }
        if ($isVpn) { continue }
        return $addr.IPAddress
    }
    return $null
}

function Get-VpnNetworkSnapshot {
    $wan = Get-WanAdapterName
    $defaultRoute = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Sort-Object RouteMetric |
        Select-Object -First 1
    $egressAdapter = $null
    if ($defaultRoute) {
        $egressAdapter = (Get-NetAdapter -InterfaceIndex $defaultRoute.ifIndex -ErrorAction SilentlyContinue).Name
    }

    $vpnAdapters = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
        $_.InterfaceDescription -match 'ExpressVPN|OpenVPN|WireGuard|Wintun|TAP|TUN|Lightway|VPN' -or
        $_.Name -match 'ExpressVPN|VPN|TAP|TUN|Lightway'
    })
    $tunnelUp = @($vpnAdapters | Where-Object { $_.Status -eq 'Up' }).Count -gt 0
    $expressRunning = $null -ne (Get-Process -Name 'expressvpn-client', 'expressvpn-service' -ErrorAction SilentlyContinue | Select-Object -First 1)

    $vpnConnected = $tunnelUp
    if (-not $vpnConnected -and $egressAdapter -and $wan) {
        $vpnConnected = ($egressAdapter -ne $wan)
    }

    $lanIp = Get-PreferredLanIp
    $signature = @(
        [bool]$vpnConnected
        [string]$egressAdapter
        [string]$wan
        [bool]$tunnelUp
        [string]$lanIp
    ) -join '|'

    return [ordered]@{
        timestamp          = (Get-Date).ToString('o')
        vpn_connected      = [bool]$vpnConnected
        egress_adapter     = $egressAdapter
        wan_adapter        = $wan
        tunnel_up          = [bool]$tunnelUp
        expressvpn_running = [bool]$expressRunning
        lan_ip             = $lanIp
        default_route_nexthop = $defaultRoute.NextHop
        signature          = $signature
    }
}

function Get-VpnNetworkState {
    if (-not (Test-Path $script:StateFile)) { return $null }
    try {
        return Get-Content $script:StateFile -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Save-VpnNetworkState {
    param($Snapshot)
    $dir = Split-Path $script:StateFile -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $Snapshot | ConvertTo-Json -Depth 4 | Set-Content -Path $script:StateFile -Encoding UTF8
}

function Test-PortOpen {
    param([int]$Port, [string]$HostName = '127.0.0.1', [int]$TimeoutMs = 800)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        $ready = $connect.AsyncWaitHandle.WaitOne($TimeoutMs)
        if ($ready -and $client.Connected) {
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

function Test-CaddyListeningOnLan {
    param([string]$LanIp)
    if (-not $LanIp) { return $false }
    return Test-PortOpen -Port 443 -HostName $LanIp
}

function Test-DockerDaemonReady {
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = 'docker'
        $psi.Arguments = 'info'
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        if (-not $proc.WaitForExit(5000)) {
            try { $proc.Kill() } catch {}
            return $false
        }
        return $proc.ExitCode -eq 0
    } catch {
        return $false
    }
}

function Test-LightStackHealthy {
    if (-not (Test-PortOpen 8096)) {
        return $false
    }

    $lanIp = Get-PreferredLanIp
    if ($lanIp -and -not (Test-CaddyListeningOnLan -LanIp $lanIp)) {
        return $false
    }

    if (-not (Test-DockerDaemonReady)) {
        return $false
    }

    foreach ($port in @(8191, 9696, 5030, 5432, 8000, 8080)) {
        if (-not (Test-PortOpen -Port $port)) {
            return $false
        }
    }

    return $true
}

function Import-DockerStackHelpers {
    if ($script:DockerStackHelpersImported) { return $true }
    if (-not (Test-Path $script:DockerStackHelpersPath)) { return $false }
    $savedVpnLog = $script:VpnRecoveryLog
    $savedStateFile = $script:StateFile
    . $script:DockerStackHelpersPath
    $script:VpnRecoveryLog = $savedVpnLog
    $script:StateFile = $savedStateFile
    $script:DockerStackHelpersImported = $true
    return $true
}

function Test-NativeMediaStackDecommissioned {
    if (Get-Command Test-NativeMediaDecommissioned -ErrorAction SilentlyContinue) {
        return [bool](Test-NativeMediaDecommissioned)
    }
    return Test-Path $script:NativeDecommissionedMarker
}

function Restore-VpnLocalNetworkRoutes {
    param($Snapshot)

    if (-not $Snapshot -or -not [bool]$Snapshot.vpn_connected) { return }

    $wan = Get-WanAdapterName
    $wanAdapter = Get-NetAdapter -Name $wan -ErrorAction SilentlyContinue
    if (-not $wanAdapter -or $wanAdapter.Status -ne 'Up') {
        Write-VpnLog "WAN adapter '$wan' unavailable; skipping LAN route restore" 'WARN'
        return
    }

    foreach ($prefix in $script:LanRoutePrefixes) {
        try {
            $existing = Get-NetRoute -DestinationPrefix $prefix -InterfaceIndex $wanAdapter.ifIndex -ErrorAction SilentlyContinue |
                Where-Object { $_.NextHop -eq '0.0.0.0' } |
                Select-Object -First 1
            if ($existing) { continue }

            New-NetRoute `
                -DestinationPrefix $prefix `
                -InterfaceIndex $wanAdapter.ifIndex `
                -NextHop '0.0.0.0' `
                -RouteMetric 1 `
                -PolicyStore ActiveStore `
                -ErrorAction Stop | Out-Null
            Write-VpnLog "Restored LAN route $prefix via $wan"
        } catch {
            Write-VpnLog "LAN route $prefix skipped: $($_.Exception.Message)" 'WARN'
        }
    }
}

function Get-SystemBootAgeMinutes {
    try {
        $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
        return [math]::Round(((Get-Date) - $boot).TotalMinutes, 1)
    } catch {
        return 9999
    }
}

function Get-DockerRestartCooldownRemainingMinutes {
    if (-not (Test-Path $script:DockerRestartCooldownFile)) { return 0 }
    try {
        $payload = Get-Content $script:DockerRestartCooldownFile -Raw | ConvertFrom-Json
        $last = [datetime]::Parse($payload.last_docker_restart)
        $elapsed = ((Get-Date) - $last).TotalMinutes
        $remaining = $script:DockerRestartCooldownMinutes - $elapsed
        if ($remaining -le 0) { return 0 }
        return [math]::Round($remaining, 1)
    } catch {
        return 0
    }
}

function Set-DockerRestartCooldownNow {
    $dir = Split-Path $script:DockerRestartCooldownFile -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    @{ last_docker_restart = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -Path $script:DockerRestartCooldownFile -Encoding UTF8
}

function Test-SignificantNetworkChange {
    param($Previous, $Current)
    if (-not $Previous -or -not $Current) { return $false }
    foreach ($field in @('vpn_connected', 'egress_adapter', 'wan_adapter', 'lan_ip', 'default_route_nexthop')) {
        if ([string]$Previous.$field -ne [string]$Current.$field) {
            return $true
        }
    }
    return $false
}

function Start-DockerDesktopGentle {
    param([int]$WaitSec = 90)

    $dockerDesktop = Join-Path ${env:ProgramFiles} 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path $dockerDesktop) {
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden -ErrorAction SilentlyContinue
    }

    $deadline = (Get-Date).AddSeconds($WaitSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerDaemonReady) {
            return $true
        }
        Start-Sleep -Seconds 5
    }
    return $false
}

function Invoke-DockerDesktopVpnRecovery {
    if (Test-DockerDaemonReady) { return $true }

    Write-VpnLog 'Docker daemon unavailable; trying gentle Docker Desktop start' 'WARN'
    if (Start-DockerDesktopGentle -WaitSec 90) {
        Write-VpnLog 'Docker daemon ready after gentle start'
        return $true
    }

    $bootAge = Get-SystemBootAgeMinutes
    if ($bootAge -lt $script:PostBootGraceMinutes) {
        Write-VpnLog "Skipping full Docker/WSL restart during post-boot grace (${bootAge}m since boot)" 'WARN'
        return $false
    }

    $dockerCooldown = Get-DockerRestartCooldownRemainingMinutes
    if ($dockerCooldown -gt 0) {
        Write-VpnLog "Skipping full Docker/WSL restart; cooldown active (${dockerCooldown}m remaining)" 'WARN'
        return $false
    }

    Write-VpnLog 'Docker daemon still unavailable; running full Docker Desktop restart' 'WARN'
    $restartScript = 'C:\ProgramData\mediapc-stack\scripts\restart-docker-desktop.ps1'
    if (-not (Test-Path $restartScript)) {
        Write-VpnLog "Docker restart script missing: $restartScript" 'ERR'
        return $false
    }

    Set-DockerRestartCooldownNow
    Invoke-HiddenScript -ScriptPath $restartScript -TimeoutSec 240
    $ready = Test-DockerDaemonReady
    if ($ready) {
        Write-VpnLog 'Docker daemon ready after full VPN recovery restart'
    } else {
        Write-VpnLog 'Docker daemon still unavailable after full VPN recovery restart' 'ERR'
    }
    return $ready
}

function Test-CoreStackHealthy {
    if (-not (Test-PortOpen 8096)) {
        return $false
    }

    $lanIp = Get-PreferredLanIp
    if ($lanIp -and -not (Test-CaddyListeningOnLan -LanIp $lanIp)) {
        return $false
    }

    if (-not (Import-DockerStackHelpers)) {
        return $true
    }
    $profile = Get-DockerMediaStackProfile
    if ($profile -eq 'native') {
        return $true
    }

    if (-not (Test-DockerDaemonReady)) {
        return $false
    }

    foreach ($check in @(Get-DockerStackPortChecks)) {
        if (-not (Test-PortOpen -Port $check.Port)) {
            return $false
        }
        if (-not $check.Url) { continue }
        try {
            $response = Invoke-WebRequest -Uri $check.Url -UseBasicParsing -TimeoutSec 6
            if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
                return $false
            }
        } catch {
            return $false
        }
    }

    return $true
}

function Get-RecoveryCooldownRemainingMinutes {
    if (-not (Test-Path $script:RecoveryCooldownFile)) { return 0 }
    try {
        $payload = Get-Content $script:RecoveryCooldownFile -Raw | ConvertFrom-Json
        $last = [datetime]::Parse($payload.last_recovery)
        $elapsed = ((Get-Date) - $last).TotalMinutes
        $remaining = $script:RecoveryCooldownMinutes - $elapsed
        if ($remaining -le 0) { return 0 }
        return [math]::Round($remaining, 1)
    } catch {
        return 0
    }
}

function Set-RecoveryCooldownNow {
    $dir = Split-Path $script:RecoveryCooldownFile -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    @{ last_recovery = (Get-Date).ToString('o') } | ConvertTo-Json | Set-Content -Path $script:RecoveryCooldownFile -Encoding UTF8
}

function Invoke-CaddyNetworkSync {
    $reloadCaddy = Join-Path $PSScriptRoot 'reload_caddy.ps1'
    if (-not (Test-Path $reloadCaddy)) { return }
    Write-VpnLog 'Syncing Caddy bind/listeners for current network'
    Invoke-HiddenScript -ScriptPath $reloadCaddy -TimeoutSec 90
}

function Invoke-HiddenScript {
    param([string]$ScriptPath, [string[]]$Arguments = @(), [int]$TimeoutSec = 300)
    $helpers = Join-Path $PSScriptRoot 'scheduled_task_helpers.ps1'
    if (Test-Path $helpers) {
        . $helpers
        Invoke-SilentPowerShell -ScriptPath $ScriptPath -ScriptArgs $Arguments -Wait | Out-Null
        return
    }
    $args = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-NonInteractive', '-WindowStyle', 'Hidden', '-File', $ScriptPath) + $Arguments
    Start-Process -FilePath 'powershell.exe' -ArgumentList $args -WindowStyle Hidden -Wait | Out-Null
}

function Invoke-MediaStackRecovery {
    Write-VpnLog 'Running media stack recovery'
    Import-DockerStackHelpers | Out-Null

    $dockerProfile = 'native'
    if (Get-Command Get-DockerMediaStackProfile -ErrorAction SilentlyContinue) {
        $dockerProfile = Get-DockerMediaStackProfile
    }

    $useDocker = ($dockerProfile -ne 'native') -or (Test-NativeMediaStackDecommissioned)
    if ($useDocker) {
        $needsRecovery = $false
        if (Get-Command Get-DockerStackPortChecks -ErrorAction SilentlyContinue) {
            foreach ($check in (Get-DockerStackPortChecks)) {
                $listening = Test-PortOpen $check.Port
                if (-not $listening) {
                    $needsRecovery = $true
                    break
                }
                if ($check.Url) {
                    try {
                        $r = Invoke-WebRequest -Uri $check.Url -UseBasicParsing -TimeoutSec 8
                        if ($r.StatusCode -lt 200 -or $r.StatusCode -ge 400) {
                            $needsRecovery = $true
                            break
                        }
                    } catch {
                        $needsRecovery = $true
                        break
                    }
                }
            }
        } else {
            $needsRecovery = -not (Test-PortOpen 8191) -or -not (Test-PortOpen 9696)
        }

        if ($needsRecovery) {
            Write-VpnLog "Docker $dockerProfile stack unhealthy; running compose recovery" 'WARN'
            if (Get-Command Invoke-DockerMediaStackRecovery -ErrorAction SilentlyContinue) {
                Invoke-DockerMediaStackRecovery -Reason 'vpn-transition' -StartupWaitSec 30 | Out-Null
            }
            Start-Sleep 10
        } elseif (Get-Command Sync-ProwlarrDockerApps -ErrorAction SilentlyContinue) {
            Write-VpnLog 'Re-syncing Prowlarr apps after network change'
            Sync-ProwlarrDockerApps
        }
        return
    }

    $stackWatchdog = 'C:\ProgramData\mediapc-stack\stack-watchdog.ps1'
    if (-not (Test-PortOpen 8191)) {
        Write-VpnLog 'FlareSolverr port closed; starting hidden launcher' 'WARN'
        if (Get-Command Start-HiddenProcess -ErrorAction SilentlyContinue) {
            Start-HiddenProcess -FilePath 'C:\ProgramData\FlareSolverr\start-flaresolverr.cmd' -TargetType cmd -WorkingDirectory 'C:\ProgramData\FlareSolverr'
        } elseif (Test-Path $stackWatchdog) {
            Invoke-HiddenScript -ScriptPath $stackWatchdog -TimeoutSec 120
            return
        }
        Start-Sleep 12
    }

    if (-not (Test-PortOpen 9696)) {
        Write-VpnLog 'Prowlarr port closed; restarting service' 'WARN'
        Restart-Service Prowlarr -ErrorAction SilentlyContinue
        Start-Sleep 8
    }

    if (-not (Test-PortOpen 5055)) {
        Write-VpnLog 'Seerr port closed; starting hidden launcher' 'WARN'
        if (Get-Command Start-HiddenProcess -ErrorAction SilentlyContinue) {
            Start-HiddenProcess -FilePath 'C:\ProgramData\Seerr\start-seerr.cmd' -TargetType cmd -WorkingDirectory 'C:\ProgramData\Seerr'
        }
        Start-Sleep 20
    }

    $syncScript = 'C:\ProgramData\mediapc-stack\link-prowlarr-apps.ps1'
    if ((Test-PortOpen 9696) -and (Test-PortOpen 8989) -and (Test-PortOpen 7878) -and (Test-Path $syncScript)) {
        try {
            Invoke-HiddenScript -ScriptPath $syncScript -TimeoutSec 180
            Write-VpnLog 'Prowlarr app/indexer sync completed'
        } catch {
            Write-VpnLog "Prowlarr sync failed: $($_.Exception.Message)" 'WARN'
        }
    }
}

function Invoke-VpnNetworkTransitionRecovery {
    param(
        $Previous,
        $Current
    )

    $prevConnected = [bool]$Previous.vpn_connected
    $nowConnected = [bool]$Current.vpn_connected
    $transition = if ($nowConnected -and -not $prevConnected) {
        'connected'
    } elseif (-not $nowConnected -and $prevConnected) {
        'disconnected'
    } else {
        'changed'
    }

    Write-VpnLog "VPN/network transition detected: $transition (egress=$($Current.egress_adapter), lan=$($Current.lan_ip))"

    $firewallScript = 'C:\ProgramData\mediapc-stack\scripts\ensure-media-stack-firewall.ps1'
    if (Test-Path $firewallScript) {
        try {
            Invoke-HiddenScript -ScriptPath $firewallScript -TimeoutSec 60
            Write-VpnLog 'Firewall rules synced for current network'
        } catch {
            Write-VpnLog "Firewall sync failed: $($_.Exception.Message)" 'WARN'
        }
    }

    Invoke-CaddyNetworkSync

    Restore-VpnLocalNetworkRoutes -Snapshot $Current
    Invoke-DockerDesktopVpnRecovery | Out-Null

    Invoke-MediaStackRecovery

    $coachHelpers = Join-Path $PSScriptRoot 'coach-stack-helpers.ps1'
    $coachDocker = $false
    if (Test-Path $coachHelpers) {
        $savedVpnLog = $script:VpnRecoveryLog
        $savedStateFile = $script:StateFile
        . $coachHelpers
        $script:VpnRecoveryLog = $savedVpnLog
        $script:StateFile = $savedStateFile
        $coachDocker = Test-CoachDockerMode
    }

    if (-not (Test-PortOpen 5432)) {
        Write-VpnLog 'PostgreSQL unavailable; skipping app recovery' 'WARN'
    } elseif ($coachDocker) {
        Write-VpnLog 'Recovering coach Docker stack after network change'
        Invoke-CoachDockerRecovery -Reason 'vpn-network' -StartupWaitSec 30 | Out-Null
    } else {
        if (-not (Test-PortOpen 8000)) {
            $apiScript = Join-Path $PSScriptRoot 'start_api_windows.ps1'
            if (Test-Path $apiScript) {
                Write-VpnLog 'Starting API after network change'
                Invoke-HiddenScript -ScriptPath $apiScript -TimeoutSec 60
            }
        }
        if (-not (Test-PortOpen 8080)) {
            $mcpScript = Join-Path $PSScriptRoot 'start_mcp_windows.ps1'
            if (Test-Path $mcpScript) {
                Write-VpnLog 'Starting MCP after network change'
                Invoke-HiddenScript -ScriptPath $mcpScript -TimeoutSec 60
            }
        }
    }

    if ($transition -eq 'disconnected') {
        Write-VpnLog 'VPN disconnected; triggering DuckDNS update'
        try {
            Start-ScheduledTask -TaskName 'DuckDNS Updater' -ErrorAction SilentlyContinue | Out-Null
        } catch {}
        $duckScript = 'C:\Caddy\duckdns-update.ps1'
        if (Test-Path $duckScript) {
            Invoke-HiddenScript -ScriptPath $duckScript -TimeoutSec 30
        }
    }

    $musicFix = Join-Path $PSScriptRoot 'music-ingest\fix_music_ingest.ps1'
    if (Test-Path $musicFix) {
        Write-VpnLog 'Verifying music ingest after network change'
        Invoke-HiddenScript -ScriptPath $musicFix -TimeoutSec 180
    }

    Write-VpnLog "Transition recovery complete ($transition)"
}

function Invoke-VpnNetworkWatchdog {
    param(
        [switch]$ForceRecovery,
        [switch]$QuickCheck
    )

    $current = Get-VpnNetworkSnapshot
    $previous = Get-VpnNetworkState
    $signatureChanged = $previous -and ([string]$previous.signature -ne [string]$current.signature)
    $significantChange = Test-SignificantNetworkChange -Previous $previous -Current $current
    $healthCheck = if ($QuickCheck) { { Test-LightStackHealthy } } else { { Test-CoreStackHealthy } }
    $unhealthy = -not (& $healthCheck)
    $cooldownRemaining = Get-RecoveryCooldownRemainingMinutes
    $shouldRecover = $ForceRecovery -or $significantChange -or ($unhealthy -and $cooldownRemaining -le 0)

    if ($QuickCheck) {
        return [ordered]@{
            changed           = [bool]$signatureChanged
            unhealthy         = [bool]$unhealthy
            should_recover    = [bool]$shouldRecover
            cooldown_minutes  = $cooldownRemaining
            recovered         = $false
            current           = $current
            previous_signature = if ($previous) { $previous.signature } else { $null }
        }
    }

    if (-not $previous) {
        Save-VpnNetworkState $current
        Write-VpnLog "Initialized VPN/network state signature=$($current.signature)"
        if ($unhealthy) {
            Write-VpnLog 'Stack unhealthy at initialization; running recovery' 'WARN'
            try {
                Invoke-VpnNetworkTransitionRecovery -Previous $current -Current $current
                Set-RecoveryCooldownNow
            } catch {
                Write-VpnLog "Recovery error: $($_.Exception.Message)" 'ERR'
            }
        }
        return [ordered]@{
            changed = $false
            recovered = [bool]$unhealthy
            unhealthy = [bool]$unhealthy
            current = $current
        }
    }

    if (-not $shouldRecover) {
        if ($unhealthy -and $cooldownRemaining -gt 0) {
            Write-VpnLog "Stack unhealthy but recovery cooldown active (${cooldownRemaining}m remaining)" 'WARN'
        }
        return [ordered]@{
            changed = [bool]$signatureChanged
            recovered = $false
            unhealthy = [bool]$unhealthy
            cooldown_minutes = $cooldownRemaining
            current = $current
            previous_signature = $previous.signature
        }
    }

    $reason = if ($ForceRecovery) { 'forced' } elseif ($significantChange) { 'network-change' } else { 'unhealthy-stack' }
    Write-VpnLog "Running recovery ($reason)"

    try {
        Invoke-VpnNetworkTransitionRecovery -Previous $previous -Current $current
        Set-RecoveryCooldownNow
    } catch {
        Write-VpnLog "Recovery error: $($_.Exception.Message)" 'ERR'
    }

    Save-VpnNetworkState $current
    return [ordered]@{
        changed = [bool]$signatureChanged
        recovered = $true
        unhealthy = [bool]$unhealthy
        reason = $reason
        current = $current
        previous_signature = $previous.signature
    }
}

function Get-VpnNetworkStatusText {
    $snap = Get-VpnNetworkSnapshot
    $state = if ($snap.vpn_connected) { 'VPN active' } else { 'VPN inactive' }
    $egress = if ($snap.egress_adapter) { $snap.egress_adapter } else { 'unknown' }
    $lan = if ($snap.lan_ip) { $snap.lan_ip } else { 'none' }
    return "$state | egress=$egress | lan=$lan"
}
