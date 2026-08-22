# Shared helpers for silent GitHub/pip tool updates.

function Write-UpdateLog {
    param(
        [string]$LogFile,
        [string]$Message
    )
    $line = "$(Get-Date -Format o) $Message"
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
    Write-Host $Message
}

function Test-IsAdministrator {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Invoke-ElevatedUpdate {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,
        [string[]]$ScriptArgs = @()
    )

    if (Test-IsAdministrator) {
        return $false
    }

    $quotedScript = '"' + $ScriptPath + '"'
    $argParts = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-NonInteractive",
        "-WindowStyle", "Hidden", "-File", $quotedScript, "-Elevated"
    )
    foreach ($arg in $ScriptArgs) {
        if ($null -ne $arg -and "$arg".Length -gt 0) {
            $argParts += $arg
        }
    }
    $argString = ($argParts | ForEach-Object {
        if ($_ -match '\s') { "`"$_`"" } else { $_ }
    }) -join " "

    $proc = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argString -WindowStyle Hidden -PassThru -Wait
    if ($proc) {
        exit $proc.ExitCode
    }
    exit 1
}

function Get-GithubRelease {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Repo
    )

    $uri = "https://api.github.com/repos/$Repo/releases/latest"
    return Invoke-RestMethod -Uri $uri -Headers @{ "User-Agent" = "endurance-coach-updater" } -TimeoutSec 60
}

function Get-ReleaseAssetUrl {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Release,
        [Parameter(Mandatory = $true)]
        [string]$Pattern
    )

    foreach ($asset in $Release.assets) {
        if ($asset.name -match $Pattern) {
            return [pscustomobject]@{
                Name = $asset.name
                Url = $asset.browser_download_url
            }
        }
    }
    return $null
}

function Get-ExeProductVersion {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    $info = (Get-Item $Path).VersionInfo
    if ($info.ProductVersion) { return $info.ProductVersion.Trim() }
    if ($info.FileVersion) { return $info.FileVersion.Trim() }
    return $null
}

function Stop-ProcessByPidFile {
    param(
        [string]$PidFile,
        [string]$ProcessName = "",
        [int[]]$Ports = @()
    )

    if (Test-Path $PidFile) {
        $pidValue = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($pidValue) {
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }

    if ($ProcessName) {
        Get-Process -Name $ProcessName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }

    foreach ($port in $Ports) {
        $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($conn in $connections) {
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
}

function Wait-PortOpen {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 30,
        [int]$IntervalMs = 500
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $connect = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
            $ready = $connect.AsyncWaitHandle.WaitOne($IntervalMs)
            if ($ready -and $client.Connected) {
                $client.Close()
                return $true
            }
            $client.Close()
        } catch {}
        Start-Sleep -Milliseconds $IntervalMs
    }
    return $false
}

function Install-GithubZipRelease {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DownloadUrl,
        [Parameter(Mandatory = $true)]
        [string]$InstallDir,
        [string]$StagingRoot = ""
    )

    if (-not $StagingRoot) {
        $StagingRoot = Join-Path $env:TEMP "endurance-coach-update"
    }
    New-Item -ItemType Directory -Force -Path $StagingRoot | Out-Null

    $zipPath = Join-Path $StagingRoot "download.zip"
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $zipPath -TimeoutSec 600 -UseBasicParsing

    $extractDir = Join-Path $StagingRoot "extract"
    if (Test-Path $extractDir) {
        Remove-Item $extractDir -Recurse -Force
    }
    Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

    $rootItems = Get-ChildItem -Path $extractDir -Force
    $exesAtRoot = @($rootItems | Where-Object { -not $_.PSIsContainer -and $_.Extension -eq ".exe" })
    if ($exesAtRoot.Count -gt 0) {
        $sourceRoot = $extractDir
    } else {
        $sourceDir = $rootItems | Where-Object { $_.PSIsContainer } | Select-Object -First 1
        if ($sourceDir) {
            $sourceRoot = $sourceDir.FullName
        } else {
            $sourceRoot = $extractDir
        }
    }

    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    foreach ($item in Get-ChildItem -Path $sourceRoot -Force) {
        $destPath = Join-Path $InstallDir $item.Name
        if (Test-Path $destPath) {
            Remove-Item $destPath -Recurse -Force
        }
        Copy-Item -Path $item.FullName -Destination $destPath -Recurse -Force
    }

    Remove-Item $StagingRoot -Recurse -Force -ErrorAction SilentlyContinue
}

function Test-VersionAtLeastTag {
    param(
        [string]$Installed,
        [string]$Tag
    )

    if (-not $Installed -or -not $Tag) { return $false }
    $installedPart = ($Installed -replace '^v', '' -split '\s+')[0]
    $targetPart = ($Tag -replace '^v', '' -split '\s+')[0]
    return $installedPart.StartsWith("$targetPart.")
        -or $installedPart -eq $targetPart
}

function Get-PipPackageVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,
        [Parameter(Mandatory = $true)]
        [string]$PackageName
    )

    $line = & $PythonExe -m pip show $PackageName 2>$null | Select-String "^Version:"
    if ($line) {
        return $line.ToString().Replace("Version:", "").Trim()
    }
    return ""
}

function Update-PipRequirements {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonExe,
        [Parameter(Mandatory = $true)]
        [string]$RequirementsFile,
        [string]$Label
    )

    if (-not (Test-Path $PythonExe)) {
        throw "$Label venv missing at $PythonExe"
    }
    if (-not (Test-Path $RequirementsFile)) {
        throw "$Label requirements missing at $RequirementsFile"
    }

    & $PythonExe -m pip install --upgrade pip wheel | Out-Null
    & $PythonExe -m pip install --upgrade -r $RequirementsFile
    if ($LASTEXITCODE -ne 0) {
        throw "$Label pip upgrade failed with exit $LASTEXITCODE"
    }
}
