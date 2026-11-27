# Configure ExpressVPN split tunnel + LAN access for the media stack.
param(
    [switch]$ApplySplitTunnel,
    [switch]$ApplyRoutes,
    [switch]$SyncFirewall,
    [switch]$RunRecoveryTest,
    [switch]$ShowOnly
)

$ErrorActionPreference = 'Continue'

. (Join-Path $PSScriptRoot 'network_vpn_helpers.ps1')

$LogFile = Join-Path (Split-Path $PSScriptRoot -Parent) 'logs\expressvpn-media-stack.log'
New-Item -ItemType Directory -Force -Path (Split-Path $LogFile -Parent) | Out-Null

function Write-SetupLog([string]$Message) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $Message
}

function Find-ExpressVpnCtl {
    $candidates = @(
        "${env:ProgramFiles}\ExpressVPN\expressvpnctl.exe",
        "${env:ProgramFiles(x86)}\ExpressVPN\expressvpnctl.exe",
        "${env:ProgramFiles(x86)}\ExpressVPN\services\expressvpnctl.exe"
    )
    return $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

function Invoke-ExpressVpnCtl {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $ctl = Find-ExpressVpnCtl
    if (-not $ctl) {
        throw 'expressvpnctl.exe not found'
    }
    $output = & $ctl @Arguments 2>&1
    return [ordered]@{
        ExitCode = $LASTEXITCODE
        Output = ($output | Out-String).Trim()
    }
}

function Normalize-SplitAppPath {
    param([string]$Path)
    if (-not $Path) { return '' }
    return ($Path -replace '\\', '/').Trim().ToLowerInvariant()
}

function Get-ExpressVpnBypassPaths {
    param([string]$RulesText)
    $paths = New-Object System.Collections.Generic.HashSet[string]
    foreach ($line in ($RulesText -split "`r?`n")) {
        $line = $line.Trim()
        if ($line -match '^bypass:(.+)$') {
            [void]$paths.Add((Normalize-SplitAppPath $Matches[1]))
        }
    }
    return @($paths)
}

function Test-ExpressVpnBypassRule {
    param(
        [string]$AppPath,
        [string[]]$ExistingPaths
    )
    return $ExistingPaths -contains (Normalize-SplitAppPath $AppPath)
}

function Add-ExpressVpnBypassApp {
    param([string]$AppPath)
    $ctl = Find-ExpressVpnCtl
    if (-not $ctl) {
        throw 'expressvpnctl.exe not found'
    }

    # Prefer Windows path separators; ExpressVPN accepts spaces when the whole
    # bypass:PATH token is one argv (paths with spaces must not be split).
    $normalized = [System.IO.Path]::GetFullPath($AppPath)
    $token = "bypass:$normalized"

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $ctl
    # Quote only the bypass token so spaces in Program Files paths stay intact.
    $psi.Arguments = "set split-app `"$token`""
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()

    $combined = (($stdout + "`n" + $stderr).Trim())
    if ($proc.ExitCode -ne 0) {
        # Fallback: cmd.exe keeps quoting rules closer to how ExpressVPN samples are written.
        $cmdLine = "`"$ctl`" set split-app `"$token`""
        $fallback = cmd.exe /c $cmdLine 2>&1 | Out-String
        return [ordered]@{
            ExitCode = $LASTEXITCODE
            Output = ($combined + "`nfallback: " + $fallback).Trim()
            Token = $token
        }
    }

    return [ordered]@{
        ExitCode = $proc.ExitCode
        Output = $combined
        Token = $token
    }
}

# Apps that should bypass the VPN for local media stack traffic.
# slskd/Soulseek runs inside Docker, so com.docker.backend.exe is the P2P path.
# Cursor must bypass so local/public MCP (endurance-coach) stays reachable with Network Lock.
$BypassApps = @(
    @{ Label = 'Caddy reverse proxy'; Path = 'C:\Caddy\caddy.exe' }
    @{ Label = 'Docker Desktop UI'; Path = "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe" }
    @{ Label = 'Docker backend (containers, slskd/Soulseek P2P)'; Path = "${env:ProgramFiles}\Docker\Docker\resources\com.docker.backend.exe" }
    @{ Label = 'WSL'; Path = "${env:ProgramFiles}\WSL\wsl.exe" }
    @{ Label = 'WSL host'; Path = "${env:ProgramFiles}\WSL\wslhost.exe" }
    @{ Label = 'Jellyfin'; Path = "${env:ProgramFiles}\Jellyfin\Server\jellyfin.exe" }
    @{ Label = 'Cursor IDE (local MCP / coach tools)'; Path = "$env:LOCALAPPDATA\Programs\cursor\Cursor.exe" }
)

Write-SetupLog 'ExpressVPN media stack setup'
Write-SetupLog (Get-VpnNetworkStatusText)

$ctl = Find-ExpressVpnCtl
$existingBypassPaths = @()
if (-not $ctl) {
    Write-SetupLog 'expressvpnctl.exe not found; install/update ExpressVPN first' 'ERR'
} else {
    Write-SetupLog "ExpressVPN CLI: $ctl"
    try {
        $splitEnabled = Invoke-ExpressVpnCtl @('get', 'splittunnel')
        $allowLan = Invoke-ExpressVpnCtl @('get', 'allowlan')
        $rules = Invoke-ExpressVpnCtl @('get', 'split-app')
        $existingBypassPaths = Get-ExpressVpnBypassPaths $rules.Output
        Write-SetupLog ("Split tunnel: {0}" -f $splitEnabled.Output)
        Write-SetupLog ("Allow LAN: {0}" -f $allowLan.Output)
        Write-SetupLog ("Current bypass rules:`n{0}" -f $rules.Output)
    } catch {
        Write-SetupLog "Could not read ExpressVPN state: $($_.Exception.Message)" 'WARN'
    }
}

Write-SetupLog ''
Write-SetupLog 'Where to find split tunnel in ExpressVPN v12+ UI:'
Write-SetupLog '  Open ExpressVPN > click your profile/account area > Profile tab > Split Tunneling'
Write-SetupLog '  (The old wording "allow selected apps to use the VPN" is gone; use Add App + Bypass VPN.)'
Write-SetupLog ''
Write-SetupLog 'Apps to add with Bypass VPN:'

$missing = @()
foreach ($app in $BypassApps) {
    $exists = Test-Path $app.Path
    $status = if ($exists) { 'found' } else { 'missing on disk' }
    Write-SetupLog ("  [{0}] {1}" -f $status, $app.Label)
    Write-SetupLog ("           {0}" -f $app.Path)
    if (-not $exists) { continue }

    if (Test-ExpressVpnBypassRule -AppPath $app.Path -ExistingPaths $existingBypassPaths) {
        Write-SetupLog '           already bypassed'
    } else {
        $missing += $app
        Write-SetupLog '           needs bypass'
    }
}

Write-SetupLog ''
Write-SetupLog 'Soulseek note: slskd runs in Docker (no Windows .exe). Bypass com.docker.backend.exe for P2P port 50460 (50300 is blocked by Windows reserved port ranges).'

if ($ApplySplitTunnel -and $ctl) {
    Write-SetupLog ''
    Write-SetupLog 'Applying ExpressVPN CLI settings...'

    $enableSplit = Invoke-ExpressVpnCtl @('set', 'splittunnel', 'true')
    Write-SetupLog ("set splittunnel true -> {0}" -f $enableSplit.Output)

    $enableLan = Invoke-ExpressVpnCtl @('set', 'allowlan', 'true')
    Write-SetupLog ("set allowlan true -> {0}" -f $enableLan.Output)

    if ($missing.Count -eq 0) {
        Write-SetupLog 'All required apps are already bypassed; nothing to add.'
    }

    foreach ($app in $missing) {
        $normalized = ($app.Path -replace '\\', '/')
        Write-SetupLog "Adding bypass: bypass:$normalized"
        $result = Add-ExpressVpnBypassApp -AppPath $app.Path
        if ($result.ExitCode -ne 0) {
            Write-SetupLog ("CLI add failed for {0}. Add manually: ExpressVPN > Profile > Split Tunneling > Add App > {1}" -f $app.Label, $app.Path) 'WARN'
        } else {
            Write-SetupLog "Added via CLI: $($app.Label)"
        }
    }

    $finalRules = Invoke-ExpressVpnCtl @('get', 'split-app')
    Write-SetupLog ("Final bypass rules:`n{0}" -f $finalRules.Output)
}

if ($ShowOnly) {
    Write-SetupLog 'ShowOnly mode; no firewall/route/recovery changes applied.'
    exit 0
}

if ($SyncFirewall) {
    $fw = 'C:\ProgramData\mediapc-stack\scripts\ensure-media-stack-firewall.ps1'
    if (Test-Path $fw) {
        Write-SetupLog 'Syncing firewall rules for LAN access on all network profiles'
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $fw
    }
}

if ($ApplyRoutes) {
    $snap = Get-VpnNetworkSnapshot
    Write-SetupLog 'Restoring LAN routes for VPN-connected local access'
    Restore-VpnLocalNetworkRoutes -Snapshot $snap
}

if ($RunRecoveryTest) {
    Write-SetupLog 'Running VPN recovery test...'
    $result = Invoke-VpnNetworkWatchdog -ForceRecovery
    Write-SetupLog ("Recovery result: recovered={0} unhealthy={1}" -f $result.recovered, $result.unhealthy)
}

if (-not $ApplySplitTunnel) {
    Write-SetupLog ''
    Write-SetupLog 'To attempt CLI setup, run:'
    Write-SetupLog '  .\scripts\configure_expressvpn_media_stack.ps1 -ApplySplitTunnel'
    Write-SetupLog 'If CLI add fails, use ExpressVPN > Profile > Split Tunneling > Add App for each path above.'
}

Write-SetupLog "Done. Log: $LogFile"
