#Requires -Version 5.1
<#
.SYNOPSIS
  First-run installer for endurance-coach on Windows.

.DESCRIPTION
  - Creates .venv and installs Python dependencies (requirements.txt + editable package)
  - Copies .env.example -> .env with user-specific fields left empty
  - Generates API_SECRET_KEY
  - Runs database migrations
  - Registers hidden scheduled tasks (API, MCP, Garmin sync, watchdog)
  - Optional: Caddy + DuckDNS reverse proxy setup

.PARAMETER InstallRoot
  Project root directory. Defaults to parent of installer/.

.PARAMETER SkipPythonInstall
  Do not attempt winget install of Python 3.12.

.PARAMETER SkipPostgresCheck
  Do not wait for PostgreSQL on port 5432.

.PARAMETER SkipScheduledTasks
  Skip Task Scheduler registration.

.PARAMETER WithCaddy
  Install optional Caddy reverse-proxy tasks (requires elevation).

.PARAMETER NonInteractive
  Use defaults only; PUBLIC_BASE_URL stays empty (local-only).
#>
param(
    [string]$InstallRoot = "",
    [switch]$SkipPythonInstall,
    [switch]$SkipPostgresCheck,
    [switch]$SkipScheduledTasks,
    [switch]$WithCaddy,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"

if (-not $InstallRoot) {
    $InstallRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$ScriptsDir = Join-Path $InstallRoot "scripts"
$EnvExample = Join-Path $InstallRoot ".env.example"
$EnvFile = Join-Path $InstallRoot ".env"
$VenvDir = Join-Path $InstallRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$LogDir = Join-Path $InstallRoot "logs"
$LocalJsonExample = Join-Path $InstallRoot "installer\local.json.example"
$LocalJson = Join-Path $InstallRoot "installer\local.json"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-CommandAvailable([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PythonVersion([string]$PythonExe) {
    $raw = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    return [version]$raw.Trim()
}

function Ensure-Python {
    if (Test-Path $VenvPython) {
        $version = Get-PythonVersion $VenvPython
        if ($version.Major -eq 3 -and $version.Minor -ge 12) {
            Write-Host "Using existing venv Python $version"
            return $VenvPython
        }
    }

    $systemPython = $null
    foreach ($candidate in @("python", "py")) {
        if (-not (Test-CommandAvailable $candidate)) { continue }
        try {
            if ($candidate -eq "py") {
                $exe = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
            } else {
                $exe = & python -c "import sys; print(sys.executable)" 2>$null
            }
            if ($exe -and (Get-PythonVersion $exe) -ge [version]"3.12") {
                $systemPython = $exe.Trim()
                break
            }
        } catch {}
    }

    if (-not $systemPython -and -not $SkipPythonInstall -and (Test-CommandAvailable "winget")) {
        Write-Step "Installing Python 3.12 via winget..."
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements | Out-Host
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
        $systemPython = (& py -3.12 -c "import sys; print(sys.executable)").Trim()
    }

    if (-not $systemPython) {
        throw "Python 3.12+ is required. Install from https://www.python.org/downloads/ or rerun without -SkipPythonInstall."
    }

    Write-Step "Creating virtual environment at $VenvDir"
    & $systemPython -m venv $VenvDir
    if (-not (Test-Path $VenvPython)) {
        throw "Failed to create virtual environment."
    }
    return $VenvPython
}

function Set-EnvValue([string]$Path, [string]$Key, [string]$Value) {
    $content = Get-Content $Path -Raw
    $escaped = [regex]::Escape($Key)
    if ($content -match "(?m)^$escaped=") {
        $content = $content -replace "(?m)^$escaped=.*$", "$Key=$Value"
    } else {
        $content = $content.TrimEnd() + "`r`n$Key=$Value`r`n"
    }
    Set-Content -Path $Path -Value $content.TrimEnd() -Encoding utf8 -NoNewline
    Add-Content -Path $Path -Value "" -Encoding utf8
}

function Initialize-EnvFile {
    Write-Step "Creating .env from template"
    if (-not (Test-Path $EnvExample)) {
        throw "Missing template: $EnvExample"
    }
    if (-not (Test-Path $EnvFile)) {
        Copy-Item $EnvExample $EnvFile
        Write-Host "Created $EnvFile"
    } else {
        Write-Host ".env already exists; leaving user values in place"
    }

    if (-not $NonInteractive) {
        $publicUrl = Read-Host "Public base URL (blank = local-only, e.g. https://yourname.duckdns.org)"
        if ($publicUrl) {
            Set-EnvValue $EnvFile "PUBLIC_BASE_URL" $publicUrl.TrimEnd('/')
        }
        $email = Read-Host "Athlete email (blank = athlete@localhost)"
        if ($email) {
            Set-EnvValue $EnvFile "DEFAULT_USER_EMAIL" $email
        } else {
            Set-EnvValue $EnvFile "DEFAULT_USER_EMAIL" "athlete@localhost"
        }
        $tz = Read-Host "Timezone IANA name [America/Denver]"
        if ($tz) {
            Set-EnvValue $EnvFile "APP_TIMEZONE" $tz
        }
    } else {
        if (-not (Select-String -Path $EnvFile -Pattern '^DEFAULT_USER_EMAIL=' -Quiet)) {
            Set-EnvValue $EnvFile "DEFAULT_USER_EMAIL" "athlete@localhost"
        }
    }

    Write-Host "Secrets left empty for you to fill later:"
    Write-Host "  STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET"
    Write-Host "  OPENAI_API_KEY / ANTHROPIC_API_KEY"
    Write-Host "  Garmin tokens via: python scripts/garmin_auth.py"
}

function Install-PythonDependencies([string]$PythonExe) {
    Write-Step "Installing Python dependencies"
    & $PythonExe -m pip install --upgrade pip wheel | Out-Host
    & $PythonExe -m pip install -r (Join-Path $InstallRoot "requirements.txt") | Out-Host
    & $PythonExe -m pip install -r (Join-Path $InstallRoot "requirements-dev.txt") | Out-Host
    & $PythonExe -m pip install -e $InstallRoot | Out-Host
}

function Wait-ForPostgres {
    if ($SkipPostgresCheck) {
        Write-Host "Skipping PostgreSQL check"
        return
    }
    Write-Step "Waiting for PostgreSQL on port 5432"
    $deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $connect = $client.BeginConnect("127.0.0.1", 5432, $null, $null)
            if ($connect.AsyncWaitHandle.WaitOne(500) -and $client.Connected) {
                $client.Close()
                Write-Host "PostgreSQL is reachable"
                return
            }
            $client.Close()
        } catch {}
        Start-Sleep -Seconds 2
    }
    Write-Warning @"
PostgreSQL not detected on port 5432.
Install options:
  winget install PostgreSQL.PostgreSQL.16
  docker compose up -d postgres
Then create DB/user matching DATABASE_URL in .env and rerun migrations:
  .venv\Scripts\python.exe -m alembic upgrade head
"@
}

function Invoke-Migrations([string]$PythonExe) {
    Write-Step "Running database migrations"
    Push-Location $InstallRoot
    try {
        & $PythonExe -m alembic upgrade head
    } finally {
        Pop-Location
    }
}

function Install-ScheduledTasks {
    if ($SkipScheduledTasks) {
        Write-Host "Skipping scheduled task registration"
        return
    }
    Write-Step "Registering Windows scheduled tasks (hidden)"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptsDir "install_all_services.ps1")
}

function Initialize-LocalJson {
    if (-not (Test-Path $LocalJson)) {
        Copy-Item $LocalJsonExample $LocalJson
        Write-Host "Created installer/local.json from template"
    }
}

function Install-CaddyOptional {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
    if (-not $isAdmin) {
        Write-Warning "Caddy install requires elevated PowerShell. Skipping."
        return
    }

    Write-Step "Optional Caddy + DuckDNS setup"
    Initialize-LocalJson
    $config = Get-Content $LocalJson -Raw | ConvertFrom-Json

    if (-not $NonInteractive) {
        $caddyRoot = Read-Host "Caddy install directory [C:\Caddy]"
        if ($caddyRoot) { $config.caddy_root = $caddyRoot }
        $config.duckdns_token = Read-Host "DuckDNS token (blank to skip DuckDNS task)"
        $config.duckdns_domain = Read-Host "DuckDNS domain (e.g. yourname)"
        $config.lan_bind_ip = Read-Host "LAN bind IP for Caddy (e.g. 192.168.1.10)"
        $wan = Read-Host "WAN adapter name for DuckDNS updater [Ethernet]"
        if ($wan) { $config.wan_adapter_name = $wan }
    }

    $config | ConvertTo-Json | Set-Content $LocalJson -Encoding utf8
    Set-EnvValue $EnvFile "CADDY_ROOT" $config.caddy_root
    Set-EnvValue $EnvFile "CADDYFILE_PATH" (Join-Path $config.caddy_root "Caddyfile")

    $caddyInstaller = Join-Path $InstallRoot "installer\caddy\Install-CaddyService.ps1"
    if (Test-Path $caddyInstaller) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $caddyInstaller -InstallRoot $InstallRoot
    }
    if ($config.duckdns_token) {
        $duckInstaller = Join-Path $InstallRoot "installer\caddy\Install-DuckDNSTask.ps1"
        if (Test-Path $duckInstaller) {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $duckInstaller -InstallRoot $InstallRoot
        }
    }
}

Write-Host "Endurance Coach installer"
Write-Host "Install root: $InstallRoot"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$python = Ensure-Python
Initialize-EnvFile
Install-PythonDependencies $python

Write-Step "Generating API secret"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptsDir "generate_api_secret.ps1")

Wait-ForPostgres
try {
    Invoke-Migrations $python
} catch {
    Write-Warning "Migrations failed: $($_.Exception.Message). Fix PostgreSQL and rerun alembic upgrade head."
}

Install-ScheduledTasks

if ($WithCaddy) {
    Install-CaddyOptional
}

Write-Host ""
Write-Host "Installation complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Garmin auth:  .venv\Scripts\python.exe scripts\garmin_auth.py"
Write-Host "  2. Start now:    powershell -File scripts\restart_app_services.ps1"
Write-Host "  3. Health check: http://127.0.0.1:8000/health"
Write-Host "  4. Strava:       set STRAVA_CLIENT_ID/SECRET in .env, then visit /api/v1/providers/strava/connect"
Write-Host ""
Write-Host "Docs: INSTALL.md"
