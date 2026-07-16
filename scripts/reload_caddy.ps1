# Sync Caddy bind IP for VPN/network changes, then reload (best-effort).
$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot ".env"

function Get-EnvValue([string]$Key) {
    if (-not (Test-Path $EnvFile)) { return $null }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^\s*$([regex]::Escape($Key))=(.*)$") {
            return $Matches[1].Trim()
        }
    }
    return $null
}

$Caddyfile = Get-EnvValue "CADDYFILE_PATH"
if (-not $Caddyfile) {
    $caddyRoot = Get-EnvValue "CADDY_ROOT"
    if ($caddyRoot) {
        $Caddyfile = Join-Path $caddyRoot "Caddyfile"
    } else {
        $Caddyfile = "C:\Caddy\Caddyfile"
    }
}
$LogDir = Join-Path (Split-Path -Parent $PSScriptRoot) "logs"
$LogFile = Join-Path $LogDir "caddy-reload.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
}

function Get-PreferredLanIp {
    $vpnPatterns = @(
        "wireguard", "openvpn", "tap", "tun", "wintun", "nord", "express",
        "proton", "zerotier", "tailscale", "hamachi", "vpn", "virtual"
    )
    $privatePattern = "^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)"

    $addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -match $privatePattern -and
            $_.IPAddress -notmatch "^127\."
        }

    foreach ($addr in $addresses) {
        $adapter = Get-NetAdapter -InterfaceIndex $addr.InterfaceIndex -ErrorAction SilentlyContinue
        if (-not $adapter -or $adapter.Status -ne "Up") { continue }

        $name = $adapter.Name.ToLower()
        $isVpn = $false
        foreach ($pattern in $vpnPatterns) {
            if ($name -like "*$pattern*") {
                $isVpn = $true
                break
            }
        }
        if ($isVpn) { continue }

        return $addr.IPAddress
    }

    return $null
}

function Sync-CaddyBind([string]$Path, [string]$LanIp) {
    $content = Get-Content $Path -Raw
    $updated = $content -replace "(?m)^(\s*)bind\s+[\d.]+", "`${1}bind $LanIp"
    if ($updated -ne $content) {
        Set-Content -Path $Path -Value $updated.TrimEnd() -Encoding utf8 -NoNewline
        Add-Content -Path $Path -Value "" -Encoding utf8
        Write-Log "Updated Caddy bind directives to $LanIp"
        return $true
    }
    return $false
}

if (-not (Test-Path $Caddyfile)) {
    Write-Log "ERROR: Caddyfile not found at $Caddyfile"
    exit 1
}

$caddyExe = Join-Path (Split-Path $Caddyfile -Parent) "caddy.exe"
if (-not (Test-Path $caddyExe)) {
    $caddy = Get-Command caddy -ErrorAction SilentlyContinue
    if (-not $caddy) {
        Write-Log "ERROR: caddy not found at $caddyExe or in PATH"
        exit 1
    }
    $caddyExe = $caddy.Source
}

$lanIp = Get-PreferredLanIp
if ($lanIp) {
    Sync-CaddyBind -Path $Caddyfile -LanIp $lanIp | Out-Null
} else {
    Write-Log "WARN: no preferred LAN IP detected; keeping existing bind directives"
}

Write-Log "Reloading Caddy from $Caddyfile via $caddyExe"
& $caddyExe reload --config $Caddyfile 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8
if ($LASTEXITCODE -eq 0) {
    Write-Log "Caddy reload succeeded"
    exit 0
}

Write-Log "Caddy reload failed (exit $LASTEXITCODE)"
exit $LASTEXITCODE
