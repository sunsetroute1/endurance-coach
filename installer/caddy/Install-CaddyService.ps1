#Requires -RunAsAdministrator
param(
    [string]$InstallRoot = ""
)

$ErrorActionPreference = "Stop"
if (-not $InstallRoot) {
    $InstallRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$LocalJson = Join-Path $InstallRoot "installer\local.json"
$Template = Join-Path $InstallRoot "installer\templates\Caddyfile.example"
$EnvFile = Join-Path $InstallRoot ".env"
$log = Join-Path $InstallRoot "logs\install-caddy.log"

function L($m) { "$(Get-Date -Format s) $m" | Tee-Object -FilePath $log -Append }

function Get-EnvValue([string]$Key) {
    if (-not (Test-Path $EnvFile)) { return $null }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^\s*$([regex]::Escape($Key))=(.*)$") {
            return $Matches[1].Trim()
        }
    }
    return $null
}

try {
    if (-not (Test-Path $LocalJson)) {
        Copy-Item (Join-Path $InstallRoot "installer\local.json.example") $LocalJson
    }
    $config = Get-Content $LocalJson -Raw | ConvertFrom-Json

    $caddyRoot = if ($config.caddy_root) { $config.caddy_root } else { "C:\Caddy" }
    $publicUrl = Get-EnvValue "PUBLIC_BASE_URL"
    if (-not $publicUrl) {
        throw "Set PUBLIC_BASE_URL in .env before installing Caddy (e.g. https://yourname.duckdns.org)"
    }
    $publicHost = ([uri]$publicUrl).Host
    $lanIp = $config.lan_bind_ip
    if (-not $lanIp) {
        throw "Set lan_bind_ip in installer/local.json before installing Caddy"
    }
    $duckToken = $config.duckdns_token
    if (-not $duckToken) {
        throw "Set duckdns_token in installer/local.json for TLS via DuckDNS"
    }

    New-Item -ItemType Directory -Force -Path $caddyRoot, (Join-Path $caddyRoot "data") | Out-Null

    $caddyfile = Join-Path $caddyRoot "Caddyfile"
    $templateText = Get-Content $Template -Raw
    $caddyText = $templateText `
        -replace '\{\{CADDY_DATA_DIR\}\}', (Join-Path $caddyRoot "data" -replace '\\', '\\') `
        -replace '\{\{PUBLIC_HOST\}\}', $publicHost `
        -replace '\{\{LAN_BIND_IP\}\}', $lanIp `
        -replace '\{\{DUCKDNS_TOKEN\}\}', $duckToken
    Set-Content -Path $caddyfile -Value $caddyText.TrimEnd() -Encoding utf8

    $vbs = Join-Path $caddyRoot "start-caddy-hidden.vbs"
    @"
Set sh = CreateObject("Wscript.Shell")
sh.CurrentDirectory = "$caddyRoot"
sh.Run "caddy.exe run --config Caddyfile --adapter caddyfile", 0, False
"@ | Set-Content -Path $vbs -Encoding ASCII

    $caddyExe = Join-Path $caddyRoot "caddy.exe"
    if (-not (Test-Path $caddyExe)) {
        L "WARN: $caddyExe not found. Download from https://caddyserver.com/download and place caddy.exe in $caddyRoot"
    }

    $taskName = "Caddy Server"
    $existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }

    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "//B `"$vbs`""
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 999 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -Hidden

    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Caddy reverse proxy for endurance-coach" | Out-Null

    L "Registered hidden scheduled task '$taskName'"
    if (Test-Path $caddyExe) {
        Start-ScheduledTask -TaskName $taskName
        L "Started Caddy task"
    }
    L "Done."
} catch {
    L "ERROR: $($_.Exception.Message)"
    exit 1
}
