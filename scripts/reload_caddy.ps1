# Sync Caddy bind IP for VPN/network changes, then reload or restart as needed.

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

        "proton", "zerotier", "tailscale", "hamachi", "vpn", "virtual",

        "wsl", "hyper-v", "vethernet", "docker", "loopback"

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

function Test-CaddyListeningOnLan([string]$LanIp) {

    if (-not $LanIp) { return $false }

    return Test-PortOpen -Port 443 -HostName $LanIp

}



function Stop-CaddyProcess([string]$ExePath) {

    $procs = @(Get-Process -Name caddy -ErrorAction SilentlyContinue)

    if ($procs.Count -eq 0) { return }

    Write-Log "Stopping $($procs.Count) Caddy process(es) for bind restart"

    foreach ($proc in $procs) {

        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue

    }

    Start-Sleep -Seconds 2

}



function Start-CaddyProcess([string]$ExePath, [string]$ConfigPath) {

    Write-Log "Starting Caddy from $ConfigPath via $ExePath"

    Start-Process -FilePath $ExePath -ArgumentList @('run', '--config', $ConfigPath) -WindowStyle Hidden

    Start-Sleep -Seconds 3

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

$bindChanged = $false

if ($lanIp) {

    $bindChanged = Sync-CaddyBind -Path $Caddyfile -LanIp $lanIp

} else {

    Write-Log "WARN: no preferred LAN IP detected; keeping existing bind directives"

}



if ($bindChanged) {

    Write-Log "Bind changed; restarting Caddy (reload does not rebind listeners)"

    Stop-CaddyProcess -ExePath $caddyExe

    Start-CaddyProcess -ExePath $caddyExe -ConfigPath $Caddyfile

    if (Test-CaddyListeningOnLan -LanIp $lanIp) {

        Write-Log "Caddy restart succeeded on $lanIp:443"

        exit 0

    }

    Write-Log "ERROR: Caddy restart did not bind $lanIp:443"

    exit 1

}



Write-Log "Reloading Caddy from $Caddyfile via $caddyExe"

& $caddyExe reload --config $Caddyfile 2>&1 | Out-File -FilePath $LogFile -Append -Encoding utf8

if ($LASTEXITCODE -eq 0 -and (Test-CaddyListeningOnLan -LanIp $lanIp)) {

    Write-Log "Caddy reload succeeded on $lanIp:443"

    exit 0

}



Write-Log "Caddy reload failed or wrong bind; restarting process"

Stop-CaddyProcess -ExePath $caddyExe

Start-CaddyProcess -ExePath $caddyExe -ConfigPath $Caddyfile

if (Test-CaddyListeningOnLan -LanIp $lanIp) {

    Write-Log "Caddy restart succeeded on $lanIp:443"

    exit 0

}



Write-Log "ERROR: Caddy did not bind $lanIp:443 after restart"

exit 1

