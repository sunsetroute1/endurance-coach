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

    $changed = $false
    if ($json.AutoStart -ne $desired) {
        $json | Add-Member -NotePropertyName AutoStart -NotePropertyValue $desired -Force
        $changed = $true
    }
    # Keep the dashboard out of the foreground. Docker only honors this with -Autostart.
    if (-not $Disable -and $json.OpenUIOnStartupDisabled -ne $true) {
        $json | Add-Member -NotePropertyName OpenUIOnStartupDisabled -NotePropertyValue $true -Force
        $changed = $true
    }
    if (-not $changed) {
        Write-Host "Docker settings already have AutoStart=$desired ($path)"
        $updated = $true
        continue
    }

    $json | ConvertTo-Json -Depth 20 | Set-Content -Path $path -Encoding UTF8
    Write-Host "Updated Docker settings in $path (AutoStart=$desired, OpenUIOnStartupDisabled=$($json.OpenUIOnStartupDisabled))"
    $updated = $true
}

if (-not $Disable) {
    $dockerDesktop = Join-Path ${env:ProgramFiles} 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path $dockerDesktop) {
        $runCmd = "`"$dockerDesktop`" -Autostart"
        Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'Docker Desktop' -Value $runCmd
        Write-Host "Startup command set to: $runCmd"
    }
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
