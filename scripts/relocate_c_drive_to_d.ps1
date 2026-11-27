# Relocate bulky C: data to D: while preserving path mappings via junctions.
# Run elevated:  powershell -ExecutionPolicy Bypass -File scripts\relocate_c_drive_to_d.ps1
param(
    [ValidateSet('Analyze', 'ArchiveNative', 'JellyfinData', 'Pagefile', 'CursorCache', 'JunctionMove', 'DockerDisk', 'All')]
    [string]$Phase = 'Analyze',
    [switch]$WhatIf,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$ArchiveRoot = 'D:\Archive\c-drive-cleanup'
$AppsRoot = 'D:\Apps'

function Test-IsAdministrator {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Write-Step([string]$Message) {
    Write-Host "==> $Message"
}

function Get-FolderSizeGB([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $bytes = (Get-ChildItem $Path -Recurse -Force -ErrorAction SilentlyContinue -File |
        Measure-Object -Property Length -Sum).Sum
    return [math]::Round(($bytes / 1GB), 2)
}

function Ensure-DriveSpace {
    param([string]$DriveLetter, [double]$RequiredGB = 5)
    $vol = Get-Volume -DriveLetter $DriveLetter -ErrorAction Stop
    $free = [math]::Round($vol.SizeRemaining / 1GB, 2)
    if ($free -lt $RequiredGB) {
        throw "Drive ${DriveLetter}: has only ${free} GB free; need at least ${RequiredGB} GB."
    }
}

function Move-FolderWithJunction {
    param(
        [Parameter(Mandatory)]
        [string]$Source,
        [Parameter(Mandatory)]
        [string]$Destination,
        [string[]]$StopProcesses = @(),
        [string[]]$StopServices = @(),
        [string[]]$StopTasks = @()
    )

    if (-not (Test-Path $Source)) {
        Write-Step "Skip missing: $Source"
        return
    }

    $sizeGB = Get-FolderSizeGB $Source
    Write-Step "Move $Source ($sizeGB GB) -> junction to $Destination"

    foreach ($task in $StopTasks) {
        Disable-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue | Out-Null
    }
    foreach ($svc in $StopServices) {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s -and $s.Status -eq 'Running') {
            if ($WhatIf) { Write-Step "Would stop service $svc"; continue }
            Stop-Service -Name $svc -Force
        }
    }
    foreach ($proc in $StopProcesses) {
        Get-Process -Name $proc -ErrorAction SilentlyContinue | ForEach-Object {
            if ($WhatIf) { Write-Step "Would stop process $($_.Name)"; return }
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
    }
    if ($StopProcesses.Count -gt 0 -and -not $WhatIf) {
        Start-Sleep -Seconds 5
        Get-Process -Name $StopProcesses -ErrorAction SilentlyContinue | ForEach-Object {
            Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 2
    }

    if ($WhatIf) { return }

    if (Test-Path $Destination) {
        if (-not (Test-Path $Source)) {
            cmd /c "mklink /J `"$Source`" `"$Destination`"" | Out-Null
            Write-Step "Created junction for existing destination: $Source"
            return
        }
        Write-Step "Syncing into existing destination: $Destination"
    } else {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }
    $robocopy = robocopy $Source $Destination /E /MOVE /R:2 /W:2 /NFL /NDL /NJH /NJS
    if ($robocopy -ge 8) {
        throw "robocopy failed for $Source (exit $robocopy)"
    }
    if (Test-Path $Source) {
        Remove-Item -Path $Source -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path $Source)) {
        cmd /c "mklink /J `"$Source`" `"$Destination`"" | Out-Null
    }
    if (-not (Test-Path $Source)) {
        throw "Junction creation failed for $Source"
    }
    Write-Step "Junction OK: $Source -> $Destination"
}

function Archive-DecommissionedNative {
    $marker = 'C:\ProgramData\docker\media-stack\native-decommissioned.marker'
    if (-not (Test-Path $marker)) {
        throw "Native decommission marker missing: $marker"
    }

    $targets = @(
        'C:\ProgramData\Seerr',
        'C:\ProgramData\Radarr',
        'C:\ProgramData\Sonarr',
        'C:\ProgramData\Prowlarr',
        'C:\ProgramData\Bazarr',
        'C:\Navidrome',
        'C:\slskd'
    )

    $stamp = Get-Date -Format 'yyyyMMdd-HHmm'
    $destRoot = Join-Path $ArchiveRoot $stamp

    foreach ($path in $targets) {
        if (-not (Test-Path $path)) { continue }
        $sizeGB = Get-FolderSizeGB $path
        $leaf = Split-Path $path -Leaf
        $dest = Join-Path $destRoot $leaf
        Write-Step "Archive $path ($sizeGB GB) -> $dest"
        if ($WhatIf) { continue }
        New-Item -ItemType Directory -Path $destRoot -Force | Out-Null
        if (Test-Path $dest) {
            Remove-Item -Path $dest -Recurse -Force -ErrorAction SilentlyContinue
        }
        takeown /f $path /r /d y 2>$null | Out-Null
        icacls $path /grant 'Administrators:F' /t /c 2>$null | Out-Null
        $robocopy = robocopy $path $dest /E /MOVE /R:2 /W:2 /NFL /NDL /NJH /NJS
        if ($robocopy -ge 8) {
            throw "robocopy failed for $path (exit $robocopy)"
        }
        if (Test-Path $path) {
            Remove-Item -Path $path -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

function Show-Analysis {
    $c = Get-Volume -DriveLetter C
    $d = Get-Volume -DriveLetter D
    Write-Host ''
    Write-Host 'Drive summary'
    Write-Host ("  C: {0} GB free / {1} GB total" -f [math]::Round($c.SizeRemaining/1GB,2), [math]::Round($c.Size/1GB,2))
    Write-Host ("  D: {0} GB free / {1} GB total" -f [math]::Round($d.SizeRemaining/1GB,2), [math]::Round($d.Size/1GB,2))
    Write-Host ''

    $rows = @(
        @{ Item = 'Docker WSL disk (docker_data.vhdx)'; Path = "$env:LOCALAPPDATA\Docker\wsl\disk"; Action = 'Docker Desktop Settings > Resources > Disk image location -> D:\Apps\Docker' },
        @{ Item = 'Jellyfin data/metadata'; Path = 'C:\ProgramData\Jellyfin'; Action = 'JunctionMove (stop Jellyfin first)' },
        @{ Item = 'Cursor chat/state cache'; Path = "$env:APPDATA\Cursor\User\globalStorage"; Action = 'JunctionMove (close Cursor first)' },
        @{ Item = 'Native *arr + Seerr (decommissioned)'; Path = 'C:\ProgramData\{Seerr,Radarr,Sonarr,Prowlarr,Bazarr}'; Action = 'ArchiveNative (~3.5 GB)' },
        @{ Item = 'Native Navidrome + slskd'; Path = 'C:\Navidrome, C:\slskd'; Action = 'ArchiveNative (Docker replaces these)' },
        @{ Item = 'NUT UPS tools'; Path = 'C:\NUT'; Action = 'JunctionMove (stop Network UPS Tools service)' },
        @{ Item = 'Tdarr server'; Path = 'C:\Tdarr'; Action = 'JunctionMove if still used' },
        @{ Item = 'Go toolchain'; Path = 'C:\gotools'; Action = 'JunctionMove (update PATH if needed)' },
        @{ Item = 'FFmpeg9 bundle'; Path = 'C:\FFmpeg9'; Action = 'JunctionMove (Jellyfin scripts reference this path)' },
        @{ Item = 'pnpm store'; Path = "$env:LOCALAPPDATA\pnpm\store"; Action = 'Set PNPM_HOME to D:\Cache\pnpm' },
        @{ Item = 'Windows pagefile'; Path = 'C:\pagefile.sys'; Action = 'Move via System Properties > Advanced > Virtual memory to D:' },
        @{ Item = 'Docker Desktop program'; Path = 'C:\Program Files\Docker'; Action = 'Reinstall to D: (optional, ~11 GB)' }
    )

    Write-Host 'Recommended relocations (largest first):'
    foreach ($row in $rows) {
        $size = if ($row.Path -like '*{*') { 'varies' } else { "$(Get-FolderSizeGB $row.Path) GB" }
        Write-Host ("  [{0}] {1}" -f $size, $row.Item)
        Write-Host ("         {0}" -f $row.Path)
        Write-Host ("         -> {0}" -f $row.Action)
    }
}

function Move-JellyfinData {
    Ensure-DriveSpace -DriveLetter D -RequiredGB 10
    $source = 'C:\ProgramData\Jellyfin'
    $destination = Join-Path $AppsRoot 'Jellyfin'
    $sourceOld = "$source.old"

    Disable-ScheduledTask -TaskName 'Jellyfin Watchdog' -ErrorAction SilentlyContinue | Out-Null
    foreach ($proc in @('jellyfin', 'Jellyfin.Windows.Tray')) {
        Get-Process -Name $proc -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 5
    Get-Process -Name 'jellyfin', 'Jellyfin.Windows.Tray' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    if (Test-Path $source) {
        takeown /f $source /r /d y 2>$null | Out-Null
        icacls $source /grant 'Administrators:F' /t /c 2>$null | Out-Null
        Write-Step "Sync $source -> $destination"
        $robocopy = robocopy $source $destination /E /COPYALL /R:2 /W:2 /NFL /NDL /NJH /NJS
        if ($robocopy -ge 8) {
            throw "robocopy sync failed for Jellyfin (exit $robocopy)"
        }
        if (Test-Path $sourceOld) {
            Remove-Item -Path $sourceOld -Recurse -Force -ErrorAction SilentlyContinue
        }
        Rename-Item -Path $source -NewName 'Jellyfin.old' -Force
        $source = $sourceOld
    }

    if (-not (Test-Path 'C:\ProgramData\Jellyfin')) {
        cmd /c "mklink /J `"C:\ProgramData\Jellyfin`" `"$destination`"" | Out-Null
    }
    if (-not (Test-Path 'C:\ProgramData\Jellyfin')) {
        throw 'Junction creation failed for C:\ProgramData\Jellyfin'
    }
    Write-Step "Junction OK: C:\ProgramData\Jellyfin -> $destination"

    if (Test-Path $sourceOld) {
        Remove-Item -Path $sourceOld -Recurse -Force -ErrorAction SilentlyContinue
    }

    Enable-ScheduledTask -TaskName 'Jellyfin Watchdog' -ErrorAction SilentlyContinue | Out-Null
    $jellyfinExe = 'C:\Program Files\Jellyfin\Server\jellyfin.exe'
    if (Test-Path $jellyfinExe) {
        Start-Process $jellyfinExe
    }
}

function Move-CursorCache {
    $source = "$env:APPDATA\Cursor\User\globalStorage"
    $destination = 'D:\Cache\Cursor\globalStorage'

    if (Test-Path $source) {
        $item = Get-Item $source -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            Write-Step "Cursor cache already junctioned: $source"
            return
        }
    }

    Ensure-DriveSpace -DriveLetter D -RequiredGB 6
    Move-FolderWithJunction `
        -Source $source `
        -Destination $destination `
        -StopProcesses @('Cursor', 'cursor')
}

function Move-PagefileToD {
    Write-Step 'Moving pagefile from C: to D: (system-managed on D:)'
    if ($WhatIf) {
        Write-Step 'Would disable C: pagefile and set D:\pagefile.sys'
        return
    }
    $cs = Get-WmiObject Win32_ComputerSystem -EnableAllPrivileges
    $cs.AutomaticManagedPagefile = $false
    $cs.Put() | Out-Null
    Get-WmiObject Win32_PageFileSetting | ForEach-Object { $_.Delete() }
    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management' `
        -Name 'PagingFiles' -Value @('D:\pagefile.sys 0 0')
    Write-Step 'Pagefile set to D:\pagefile.sys (reboot required to reclaim C: space)'
}

function Invoke-JunctionMoves {
    Ensure-DriveSpace -DriveLetter D -RequiredGB 30

    Move-JellyfinData

    Move-FolderWithJunction `
        -Source 'C:\NUT' `
        -Destination (Join-Path $AppsRoot 'NUT') `
        -StopServices @('Network UPS Tools')

    Move-FolderWithJunction `
        -Source 'C:\Tdarr' `
        -Destination (Join-Path $AppsRoot 'Tdarr') `
        -StopProcesses @('Tdarr_Server', 'Tdarr_Server_Tray')

    Move-FolderWithJunction `
        -Source 'C:\gotools' `
        -Destination (Join-Path $AppsRoot 'gotools')

    Move-FolderWithJunction `
        -Source 'C:\FFmpeg9' `
        -Destination (Join-Path $AppsRoot 'FFmpeg9')

    Move-FolderWithJunction `
        -Source "$env:APPDATA\Cursor\User\globalStorage" `
        -Destination 'D:\Cache\Cursor\globalStorage' `
        -StopProcesses @('Cursor', 'cursor')
}

function Show-DockerDiskInstructions {
    Write-Host ''
    Write-Host 'Docker disk image move (manual, ~14 GB):'
    Write-Host '  1. Quit Docker Desktop completely (tray icon > Quit).'
    Write-Host '  2. Open Docker Desktop > Settings > Resources > Advanced.'
    Write-Host '  3. Set "Disk image location" to D:\Apps\Docker'
    Write-Host '  4. Apply & Restart. Docker migrates docker_data.vhdx automatically.'
    Write-Host ''
    Write-Host 'Do NOT manually move docker_data.vhdx while Docker is running.'
}

if (-not (Test-IsAdministrator)) {
    throw 'Run this script elevated (Run as administrator).'
}

Ensure-DriveSpace -DriveLetter D -RequiredGB 10

switch ($Phase) {
    'Analyze' { Show-Analysis; Show-DockerDiskInstructions }
    'ArchiveNative' { Archive-DecommissionedNative }
    'JellyfinData' { Move-JellyfinData }
    'Pagefile' { Move-PagefileToD }
    'CursorCache' { Move-CursorCache }
    'JunctionMove' { Invoke-JunctionMoves }
    'DockerDisk' { Show-DockerDiskInstructions }
    'All' {
        Archive-DecommissionedNative
        Invoke-JunctionMoves
        Show-DockerDiskInstructions
    }
}

Write-Host ''
Write-Host 'Done.' -ForegroundColor Green
