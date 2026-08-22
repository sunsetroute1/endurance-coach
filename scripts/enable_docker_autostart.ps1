# Ensure Docker Desktop starts automatically when the user session begins (after auto-login).
param(
    [switch]$Disable
)

$ErrorActionPreference = 'Stop'

$settingsPaths = @(
    (Join-Path $env:APPDATA 'Docker\settings-store.json'),
    (Join-Path $env:APPDATA 'Docker\settings.json')
)

$updated = $false
foreach ($path in $settingsPaths) {
    if (-not (Test-Path $path)) {
        continue
    }

    $raw = Get-Content -Path $path -Raw -Encoding UTF8
    $json = $raw | ConvertFrom-Json
    $desired = -not $Disable

    if ($json.AutoStart -eq $desired) {
        Write-Host "Docker settings already have AutoStart=$desired ($path)"
        $updated = $true
        continue
    }

    $json.AutoStart = $desired
    $json | ConvertTo-Json -Depth 20 | Set-Content -Path $path -Encoding UTF8
    Write-Host "Set Docker AutoStart=$desired in $path"
    $updated = $true
}

if (-not $updated) {
    Write-Warning 'No Docker settings file found. Install Docker Desktop first, then re-run this script.'
    exit 1
}

if ($Disable) {
    Write-Host 'Docker Desktop will no longer auto-start with the user session.'
} else {
    Write-Host 'Docker Desktop will auto-start when you log in (including auto-login after reboot).'
}
