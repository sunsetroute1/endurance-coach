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

function Log(`$m){ "`$(Get-Date -Format s) `$m" | Add-Content -Path `$log }

try {
    `$def = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric | Select-Object -First 1
    `$egress = if (`$def) { (Get-NetAdapter -InterfaceIndex `$def.ifIndex -ErrorAction SilentlyContinue).Name } else { `$null }
    if (`$egress -ne `$wanName) {
        Log "SKIP egress=`$egress (VPN active or non-WAN egress); DuckDNS left unchanged"
    } else {
        `$resp = (Invoke-RestMethod -Uri "https://www.duckdns.org/update?domains=`$domain&token=`$token&ip=" -TimeoutSec 25)
        Log ("`$(`"`$resp`").Trim()) egress=`$egress"
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
