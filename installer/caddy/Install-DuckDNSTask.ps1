#Requires -RunAsAdministrator
param(
    [string]$InstallRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $InstallRoot) {
    $InstallRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$LocalJson = Join-Path $InstallRoot "installer\local.json"
$log = Join-Path $InstallRoot "logs\install-duckdns.log"

function L($m) { "$(Get-Date -Format s) $m" | Tee-Object -FilePath $log -Append }

try {
    if (-not (Test-Path $LocalJson)) {
        throw "Missing $LocalJson - run installer with -WithCaddy first"
    }
    $config = Get-Content $LocalJson -Raw | ConvertFrom-Json
    if (-not $config.duckdns_token -or -not $config.duckdns_domain) {
        throw "Set duckdns_token and duckdns_domain in installer/local.json"
    }

    $caddyRoot = if ($config.caddy_root) { $config.caddy_root } else { "C:\Caddy" }
    New-Item -ItemType Directory -Force -Path $caddyRoot | Out-Null

    $updateScript = Join-Path $caddyRoot "duckdns-update.ps1"
    $wanName = if ($config.wan_adapter_name) { $config.wan_adapter_name } else { "Ethernet" }
    @"
`$ErrorActionPreference = 'SilentlyContinue'
`$token   = '$($config.duckdns_token)'
`$domain  = '$($config.duckdns_domain)'
`$log     = '$caddyRoot\duckdns.log'
`$wanName = '$wanName'

function Log(`$m) { "`$(Get-Date -Format s) `$m" | Add-Content -Path `$log }

function Get-PublicIp {
    `$bind = `$null
    try {
        `$bind = Get-NetIPAddress -InterfaceAlias `$wanName -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { `$_.IPAddress -notlike '169.254.*' } |
            Select-Object -ExpandProperty IPAddress -First 1
    } catch {}
    if (-not `$bind) { return `$null }
    `$curl = Join-Path `$env:SystemRoot 'System32\curl.exe'
    foreach (`$url in @('https://api.ipify.org', 'https://ifconfig.me/ip', 'https://icanhazip.com')) {
        try {
            `$ip = (& `$curl --interface `$bind -4 -sS --max-time 15 `$url).ToString().Trim()
            if (`$ip -match '^\d{1,3}(\.\d{1,3}){3}$') { return `$ip }
        } catch {}
    }
    return `$null
}

function Get-DnsIp([string]`$HostName) {
    try {
        return (Resolve-DnsName -Name `$HostName -Type A -Server 1.1.1.1 -DnsOnly -ErrorAction Stop |
            Where-Object { `$_.Type -eq 'A' } |
            Select-Object -ExpandProperty IPAddress -First 1)
    } catch { return `$null }
}

try {
    `$def = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1
    `$egress = if (`$def) { (Get-NetAdapter -InterfaceIndex `$def.ifIndex -ErrorAction SilentlyContinue).Name } else { `$null }
    `$hostname = "`$domain.duckdns.org"
    `$publicIp = Get-PublicIp
    if (`$egress -ne `$wanName) {
        Log "SKIP egress=`$egress public=`$publicIp dns=`$(Get-DnsIp `$hostname) (VPN active; DuckDNS left unchanged)"
    } elseif (-not `$publicIp) {
        Log "SKIP egress=`$egress public=none (no WAN address via `$wanName; DuckDNS left unchanged)"
    } else {
        `$uri = "https://www.duckdns.org/update?domains=`$domain&token=`$token&ip=`$publicIp&verbose=true"
        `$resp = (Invoke-RestMethod -Uri `$uri -TimeoutSec 25).ToString().Trim()
        Start-Sleep -Seconds 2
        `$dnsIp = Get-DnsIp `$hostname
        if (`$dnsIp -and `$publicIp -and `$dnsIp -ne `$publicIp) {
            Log "WARN resp=`$resp egress=`$egress public=`$publicIp dns=`$dnsIp (mismatch)"
        } else {
            Log "OK resp=`$resp egress=`$egress public=`$publicIp dns=`$dnsIp"
        }
    }
    `$lines = Get-Content `$log -ErrorAction SilentlyContinue
    if (`$lines.Count -gt 500) { `$lines | Select-Object -Last 300 | Set-Content `$log }
} catch {
    Log "ERROR `$(`$_.Exception.Message)"
}
"@ | Set-Content -Path $updateScript -Encoding utf8

    $taskName = "DuckDNS Updater"
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }

    $helpers = Join-Path $InstallRoot "scripts\scheduled_task_helpers.ps1"
    if (Test-Path $helpers) {
        . $helpers
        $action = New-SilentPowerShellTaskAction -ScriptPath $updateScript
    } else {
        $action = New-ScheduledTaskAction `
            -Execute "powershell.exe" `
            -Argument "-NoProfile -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File `"$updateScript`""
    }
    $tAtStart = New-ScheduledTaskTrigger -AtStartup
    $tRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
        -Hidden

    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $tAtStart, $tRepeat `
        -Principal $principal `
        -Settings $settings `
        -Description "Keeps DuckDNS hostname pointed at current public IP" | Out-Null

    L "Registered hidden '$taskName'"
    Start-ScheduledTask -TaskName $taskName
    L "Done."
} catch {
    L "ERROR: $($_.Exception.Message)"
    exit 1
}
