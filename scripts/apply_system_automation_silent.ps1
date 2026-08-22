# Re-apply hidden/minimized settings for all known automation on this machine.
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "Re-registering endurance-coach scheduled tasks (hidden)..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install_all_services.ps1")

$adminScripts = @(
    (Join-Path $ProjectRoot "installer\caddy\Install-CaddyService.ps1"),
    (Join-Path $ProjectRoot "installer\caddy\Install-DuckDNSTask.ps1")
)

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if ($isAdmin) {
    foreach ($script in $adminScripts) {
        if (-not (Test-Path $script)) {
            Write-Warning "Skipping missing script: $script"
            continue
        }
        Write-Host "Running $script..."
        try {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -InstallRoot $ProjectRoot
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "$script exited with code $LASTEXITCODE (non-fatal for core services)"
            }
        } catch {
            Write-Warning "$script failed: $($_.Exception.Message) (non-fatal for core services)"
        }
    }
} else {
    Write-Host ""
    Write-Host "Skipped Caddy/DuckDNS task updates (admin required)."
    Write-Host "Run elevated:"
    foreach ($script in $adminScripts) {
        Write-Host "  powershell -ExecutionPolicy Bypass -File `"$script`" -InstallRoot `"$ProjectRoot`""
    }
}

Write-Host ""
Write-Host "Hidden task verification:"
$taskNames = @(
    "EnduranceCoachAPI",
    "EnduranceCoachMCP",
    "EnduranceCoachGarminSync",
    "EnduranceCoachWatchdog",
    "MusicIngestWatcher",
    "MusicIngestFallbackScan",
    "Slskd",
    "VPN Network Watchdog",
    "Media Stack Boot",
    "Media Server Post-Boot Recovery",
    "AutomationWatchboard",
    "Caddy Server",
    "DuckDNS Updater"
)
foreach ($name in $taskNames) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host ("  {0,-28} missing" -f $name)
        continue
    }
    $args = $task.Actions.Arguments
    $hidden = $task.Settings.Hidden
    $silent = ($args -match 'WindowStyle Hidden') -or ($task.Actions.Execute -eq 'wscript.exe')
    Write-Host ("  {0,-28} Hidden={1} SilentLauncher={2}" -f $name, $hidden, $silent)
}

Write-Host ""
Write-Host "Running service repair + Garmin sync catch-up..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "fix_endurance_services.ps1")
exit $LASTEXITCODE
