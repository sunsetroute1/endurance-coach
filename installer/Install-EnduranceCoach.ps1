#Requires -Version 5.1
<#
.SYNOPSIS
  First-run installer for endurance-coach on Windows.

.DESCRIPTION
  - Creates .venv and installs Python dependencies (requirements.txt + editable package)
  - Copies .env.example -> .env with user-specific fields left empty
  - Generates API_SECRET_KEY
  - Merges missing .env keys and MCP defaults (idempotent)
  - Runs database migrations
  - Registers hidden scheduled tasks (API, MCP, Garmin sync, watchdog)
  - Optional: Docker mode (coach-active.marker + compose recovery)
  - Optional: Caddy + DuckDNS reverse proxy setup
  - Optional: Repair mode (non-interactive merge / recover / health)

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

.PARAMETER Docker
  Enable Docker mode (create coach-active.marker, compose up via recovery).

.PARAMETER Repair
  Repair path: merge env, schedules, stack recover, health checks; skip wizard prompts.

.PARAMETER SkipGarminAuth
  Skip garmin_auth.py gate.

.PARAMETER RunGarminAuth
  Force interactive Garmin auth after Python deps.
#>
param(
    [string]$InstallRoot = "",
    [switch]$SkipPythonInstall,
    [switch]$SkipPostgresCheck,
    [switch]$SkipScheduledTasks,
    [switch]$WithCaddy,
    [switch]$NonInteractive,
    [switch]$Docker,
    [switch]$Repair,
    [switch]$SkipGarminAuth,
    [switch]$RunGarminAuth
)

$ErrorActionPreference = "Stop"

if (-not $InstallRoot) {
    $InstallRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

# Repair uses NonInteractive prompt behavior
if ($Repair) {
    $NonInteractive = $true
}

$ScriptsDir = Join-Path $InstallRoot "scripts"
$EnvExample = Join-Path $InstallRoot ".env.example"
$EnvFile = Join-Path $InstallRoot ".env"
$VenvDir = Join-Path $InstallRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$LogDir = Join-Path $InstallRoot "logs"
$LocalJsonExample = Join-Path $InstallRoot "installer\local.json.example"
$LocalJson = Join-Path $InstallRoot "installer\local.json"
$DockerMarker = Join-Path $InstallRoot "coach-active.marker"
$CoachStackHelpers = Join-Path $ScriptsDir "coach-stack-helpers.ps1"

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

function Get-EnvValueFromFile([string]$Path, [string]$Key) {
    if (-not (Test-Path $Path)) { return $null }
    foreach ($line in Get-Content $Path) {
        if ($line -match "^\s*$([regex]::Escape($Key))=(.*)$") {
            return $Matches[1].Trim()
        }
    }
    return $null
}

function Test-EnvKeyMissingOrEmpty([string]$Path, [string]$Key) {
    $value = Get-EnvValueFromFile $Path $Key
    return ($null -eq $value -or $value -eq "")
}

function Merge-MissingEnvKeysFromExample {
    if (-not (Test-Path $EnvExample)) {
        Write-Warning "Missing .env.example; cannot merge missing keys."
        return
    }
    if (-not (Test-Path $EnvFile)) {
        Copy-Item $EnvExample $EnvFile
        Write-Host "Created $EnvFile from .env.example"
        return
    }

    $existing = @{}
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^\s*([A-Za-z_][A-Za-z0-9_]*)=") {
            $existing[$Matches[1]] = $true
        }
    }

    $added = 0
    foreach ($line in Get-Content $EnvExample) {
        if ($line -match "^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$") {
            $key = $Matches[1]
            $exampleValue = $Matches[2]
            if (-not $existing.ContainsKey($key)) {
                Add-Content -Path $EnvFile -Value "$key=$exampleValue" -Encoding utf8
                $existing[$key] = $true
                $added++
            }
        }
    }
    if ($added -gt 0) {
        Write-Host "Merged $added missing key(s) from .env.example into .env"
    }
}

function Ensure-McpEnvDefaults {
    Write-Step "Ensuring MCP / .env defaults"
    Merge-MissingEnvKeysFromExample

    if (-not (Test-Path $EnvFile)) {
        throw "Missing .env at $EnvFile"
    }

    # Force defaults only when key is missing or empty (never clobber non-empty values)
    $forceIfBlank = @{
        "MCP_STATELESS_HTTP"           = "true"
        "MCP_JSON_RESPONSE"            = "true"
        "MCP_ADVERTISE_OAUTH_RESOURCE" = "false"
        "MCP_TRANSPORT"                = "streamable-http"
        "MCP_HOST"                     = "127.0.0.1"
        "MCP_PORT"                     = "8080"
    }
    foreach ($key in $forceIfBlank.Keys) {
        if (Test-EnvKeyMissingOrEmpty $EnvFile $key) {
            Set-EnvValue $EnvFile $key $forceIfBlank[$key]
            Write-Host "Set $key=$($forceIfBlank[$key])"
        }
    }
}

function Read-SettingPrompt {
    param(
        [string]$Label,
        [string]$Default = "",
        [switch]$Secret,
        [switch]$AllowBlank
    )

    if ($NonInteractive) {
        return $Default
    }

    $suffix = if ($Default) { " [$Default]" } else { "" }
    if ($AllowBlank) { $suffix += " (Enter to skip)" }

    if ($Secret) {
        $secure = Read-Host "$Label$suffix" -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        )
        if (-not $plain -and $Default) { return $Default }
        return $plain
    }

    $value = Read-Host "$Label$suffix"
    if (-not $value) {
        if ($AllowBlank) { return "" }
        return $Default
    }
    return $value.Trim()
}

function New-ApiSecretKey {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Set-GarminAlertSettings {
    if ($NonInteractive) { return }

    Write-Host ""
    Write-Host "Garmin token alerts" -ForegroundColor Yellow
    Write-Host "When Garmin rejects the saved token, one alert is sent. The alert does not contain the Garmin password."
    Write-Host "The link opens a sign-in page hosted by this server, at PUBLIC_BASE_URL/api/v1/garmin/login."
    Write-Host "That page has to run on this computer, because the Garmin login call is made from here."
    Write-Host "You type the Garmin email, password, and verification code on that page."
    Write-Host "The password is used only for that sign-in. It is not saved, not written to disk, and not sent to the alert service."
    Write-Host "The same rule applies to the local script, scripts\garmin_auth.py, if you sign in at this computer."
    $publicNow = Get-EnvValueFromFile $EnvFile "PUBLIC_BASE_URL"
    if (-not $publicNow) {
        Write-Host "PUBLIC_BASE_URL is empty, so a phone cannot open that page yet. Set a URL the phone can reach, or sign in with the local script." -ForegroundColor Yellow
    }
    Write-Host "  1  ntfy.sh (default, free). Install the ntfy app and subscribe to a topic. An access token also emails the alert."
    Write-Host "  2  Email through your own mail server."
    Write-Host "  3  Another SMS or alert service, via an HTTPS webhook you provide."
    Write-Host "  4  No alert. Sign in on this computer when sync pauses."
    $currentProvider = Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_PROVIDER"
    if (-not $currentProvider) { $currentProvider = "1" }
    $choiceDefault = switch ($currentProvider.ToLower()) {
        "email" { "2" }
        "webhook" { "3" }
        "sms" { "3" }
        "none" { "4" }
        default { "1" }
    }
    $choice = Read-SettingPrompt -Label "Alert choice" -Default $choiceDefault

    switch ($choice) {
        "2" {
            Set-EnvValue $EnvFile "GARMIN_ALERT_PROVIDER" "email"
            $to = Read-SettingPrompt -Label "Alert email address" -Default (Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_EMAIL_TO")
            if ($to) { Set-EnvValue $EnvFile "GARMIN_ALERT_EMAIL_TO" $to }
            $smtpDefault = Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_SMTP_HOST"
            $smtpHost = Read-SettingPrompt -Label "SMTP server" -Default $smtpDefault
            if ($smtpHost) { Set-EnvValue $EnvFile "GARMIN_ALERT_SMTP_HOST" $smtpHost }
            $portDefault = Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_SMTP_PORT"
            if (-not $portDefault) { $portDefault = "587" }
            $port = Read-SettingPrompt -Label "SMTP port" -Default $portDefault
            if ($port) { Set-EnvValue $EnvFile "GARMIN_ALERT_SMTP_PORT" $port }
            $user = Read-SettingPrompt -Label "SMTP username" -Default (Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_SMTP_USER") -AllowBlank
            if ($user) { Set-EnvValue $EnvFile "GARMIN_ALERT_SMTP_USER" $user }
            if (Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_SMTP_PASSWORD") {
                Write-Host "SMTP password: already set (Enter to keep). This is the mailbox password, not the Garmin password."
            } else {
                Write-Host "SMTP password is the mailbox password, not the Garmin password."
            }
            $smtpPassword = Read-SettingPrompt -Label "SMTP password" -AllowBlank -Secret
            if ($smtpPassword) { Set-EnvValue $EnvFile "GARMIN_ALERT_SMTP_PASSWORD" $smtpPassword }
            $fromDefault = Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_SMTP_FROM"
            if (-not $fromDefault) { $fromDefault = $user }
            $from = Read-SettingPrompt -Label "From address" -Default $fromDefault -AllowBlank
            if ($from) { Set-EnvValue $EnvFile "GARMIN_ALERT_SMTP_FROM" $from }
        }
        "3" {
            Set-EnvValue $EnvFile "GARMIN_ALERT_PROVIDER" "webhook"
            Write-Host "The webhook receives the alert text and the sign-in link. It does not receive the Garmin password."
            $url = Read-SettingPrompt -Label "HTTPS webhook URL" -Default (Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_WEBHOOK_URL") -AllowBlank
            if ($url) { Set-EnvValue $EnvFile "GARMIN_ALERT_WEBHOOK_URL" $url }
            $header = Read-SettingPrompt -Label "Optional header, Name: value" -AllowBlank
            if ($header) { Set-EnvValue $EnvFile "GARMIN_ALERT_WEBHOOK_HEADER" $header }
            Write-Host "Leave the body empty to send JSON with title, message, and link."
            Write-Host "Or supply a body template. {message} and {link} are replaced. There is no password placeholder."
            $body = Read-SettingPrompt -Label "Optional body template" -AllowBlank
            if ($body) { Set-EnvValue $EnvFile "GARMIN_ALERT_WEBHOOK_BODY" $body }
        }
        "4" {
            Set-EnvValue $EnvFile "GARMIN_ALERT_PROVIDER" "none"
            Write-Host "Alerts are off. When the token expires, run scripts\garmin_auth.py on this computer."
        }
        default {
            Set-EnvValue $EnvFile "GARMIN_ALERT_PROVIDER" "ntfy"
            Write-Host "Default is ntfy.sh, the free phone notification used by this server."
            Write-Host "Install the ntfy app and subscribe to the topic. The alert's Sign in action opens this server's page."
            $topic = Read-SettingPrompt -Label "ntfy topic name" -Default (Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_NTFY_TOPIC") -AllowBlank
            if ($topic) { Set-EnvValue $EnvFile "GARMIN_ALERT_NTFY_TOPIC" $topic }
            $serverDefault = Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_NTFY_SERVER"
            if (-not $serverDefault) { $serverDefault = "https://ntfy.sh" }
            $server = Read-SettingPrompt -Label "ntfy server" -Default $serverDefault
            if ($server -and $server -ne "https://ntfy.sh") {
                Set-EnvValue $EnvFile "GARMIN_ALERT_NTFY_SERVER" $server.TrimEnd("/")
            }
            if (Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_NTFY_TOKEN") {
                Write-Host "ntfy access token: already set (Enter to keep). It emails the alert to the address on that ntfy account."
            } else {
                Write-Host "Optional ntfy access token. When set, ntfy also emails the alert. Enter to skip."
            }
            $token = Read-SettingPrompt -Label "ntfy access token" -AllowBlank -Secret
            if ($token) { Set-EnvValue $EnvFile "GARMIN_ALERT_NTFY_TOKEN" $token }
        }
    }
}

function Initialize-EnvFile {
    Write-Step "Setup wizard - configure your deployment"
    if (-not (Test-Path $EnvExample)) {
        throw "Missing template: $EnvExample"
    }
    if (-not (Test-Path $EnvFile)) {
        Copy-Item $EnvExample $EnvFile
        Write-Host "Created $EnvFile"
    } else {
        Write-Host ".env already exists - empty fields will be filled; existing values are kept unless you enter new ones."
    }

    if ($NonInteractive) {
        if (-not (Get-EnvValueFromFile $EnvFile "DEFAULT_USER_EMAIL")) {
            Set-EnvValue $EnvFile "DEFAULT_USER_EMAIL" "athlete@localhost"
        }
        return @{
            ApiSecretKey = Get-EnvValueFromFile $EnvFile "API_SECRET_KEY"
            PublicBaseUrl = Get-EnvValueFromFile $EnvFile "PUBLIC_BASE_URL"
        }
    }

    Write-Host ""
    Write-Host "Database" -ForegroundColor Yellow
    $dbDefault = Get-EnvValueFromFile $EnvFile "DATABASE_URL"
    if (-not $dbDefault) {
        $dbDefault = "postgresql+asyncpg://endurance:endurance@localhost:5432/endurance_coach"
    }
    $databaseUrl = Read-SettingPrompt -Label "PostgreSQL DATABASE_URL" -Default $dbDefault
    if ($databaseUrl) { Set-EnvValue $EnvFile "DATABASE_URL" $databaseUrl }

    Write-Host ""
    Write-Host "Athlete profile" -ForegroundColor Yellow
    $emailDefault = Get-EnvValueFromFile $EnvFile "DEFAULT_USER_EMAIL"
    if (-not $emailDefault) { $emailDefault = "athlete@localhost" }
    $email = Read-SettingPrompt -Label "Athlete email" -Default $emailDefault
    Set-EnvValue $EnvFile "DEFAULT_USER_EMAIL" $email

    $tzDefault = Get-EnvValueFromFile $EnvFile "APP_TIMEZONE"
    if (-not $tzDefault) { $tzDefault = "America/Denver" }
    $tz = Read-SettingPrompt -Label "Timezone (IANA)" -Default $tzDefault
    Set-EnvValue $EnvFile "APP_TIMEZONE" $tz

    Write-Host ""
    Write-Host "Public access & MCP" -ForegroundColor Yellow
    $publicDefault = Get-EnvValueFromFile $EnvFile "PUBLIC_BASE_URL"
    $publicUrl = Read-SettingPrompt -Label "Public base URL" -Default $publicDefault -AllowBlank
    if ($publicUrl) {
        Set-EnvValue $EnvFile "PUBLIC_BASE_URL" $publicUrl.TrimEnd('/')
    } elseif ($publicDefault) {
        Set-EnvValue $EnvFile "PUBLIC_BASE_URL" $publicDefault.TrimEnd('/')
    } else {
        Set-EnvValue $EnvFile "PUBLIC_BASE_URL" ""
    }

    $existingSecret = Get-EnvValueFromFile $EnvFile "API_SECRET_KEY"
    Write-Host ""
    Write-Host "API secret (Bearer token for MCP / Perplexity / API clients)" -ForegroundColor Yellow
    if ($existingSecret) {
        Write-Host "Current key is already set. Press Enter to keep it, or paste a new one."
    } else {
        Write-Host "Press Enter to auto-generate a secure key, or paste your own."
    }
    $secretInput = Read-SettingPrompt -Label "API_SECRET_KEY" -AllowBlank
    if ($secretInput) {
        Set-EnvValue $EnvFile "API_SECRET_KEY" $secretInput
        $apiSecret = $secretInput
    } elseif ($existingSecret) {
        $apiSecret = $existingSecret
    } else {
        $apiSecret = New-ApiSecretKey
        Set-EnvValue $EnvFile "API_SECRET_KEY" $apiSecret
        Write-Host "Generated a new API secret." -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Assistant connection" -ForegroundColor Yellow
    Write-Host "  1  Your own MCP client. Claude, Cursor, ChatGPT, Perplexity, LM Studio, or any other app that speaks MCP."
    Write-Host "     This server does not need that app's API key. The same bearer token also works for REST."
    Write-Host "  2  This server calls a model for the built-in coach. OpenAI, Anthropic, Ollama, or any OpenAI-compatible URL."
    $assistantChoice = Read-SettingPrompt -Label "Choice" -Default "1"
    if ($assistantChoice -eq "2") {
        $providerDefault = Get-EnvValueFromFile $EnvFile "COACH_LLM_PROVIDER"
        if (-not $providerDefault) { $providerDefault = "openai" }
        $provider = (Read-SettingPrompt -Label "Provider (openai, anthropic, ollama, local)" -Default $providerDefault).ToLower()
        if ($provider -eq "local") { $provider = "openai_compatible" }
        Set-EnvValue $EnvFile "COACH_LLM_PROVIDER" $provider

        $modelDefault = Get-EnvValueFromFile $EnvFile "COACH_LLM_MODEL"
        if (-not $modelDefault) {
            $modelDefault = switch ($provider) {
                "anthropic" { "claude-sonnet-4-5" }
                "ollama" { "llama3.1" }
                default { "gpt-4o-mini" }
            }
        }
        $model = Read-SettingPrompt -Label "Model name" -Default $modelDefault
        if ($model) { Set-EnvValue $EnvFile "COACH_LLM_MODEL" $model }

        if ($provider -eq "ollama" -or $provider -eq "openai_compatible") {
            $urlDefault = Get-EnvValueFromFile $EnvFile "COACH_LLM_BASE_URL"
            if (-not $urlDefault -and $provider -eq "ollama") { $urlDefault = "http://127.0.0.1:11434/v1" }
            $baseUrl = Read-SettingPrompt -Label "Model base URL" -Default $urlDefault
            if ($baseUrl) { Set-EnvValue $EnvFile "COACH_LLM_BASE_URL" $baseUrl.TrimEnd('/') }
        }
        if ($provider -eq "openai" -or $provider -eq "openai_compatible") {
            $key = Read-SettingPrompt -Label "OpenAI-compatible API key (Enter to skip)" -AllowBlank -Secret
            if ($key) { Set-EnvValue $EnvFile "OPENAI_API_KEY" $key }
        }
        if ($provider -eq "anthropic") {
            $key = Read-SettingPrompt -Label "Anthropic API key" -AllowBlank -Secret
            if ($key) { Set-EnvValue $EnvFile "ANTHROPIC_API_KEY" $key }
        }
    } else {
        Write-Host "No model key required. Connect any MCP client with the JSON printed at the end."
    }

    Write-Host ""
    Write-Host "Optional (Enter to skip each)" -ForegroundColor Yellow
    foreach ($pair in @(
            @{ Key = "MCP_ALLOWED_ORIGINS"; Label = "Extra MCP site origins, comma-separated (only if a browser client is rejected)" }
        )) {
        $current = Get-EnvValueFromFile $EnvFile $pair.Key
        if ($current) {
            Write-Host "$($pair.Label): already set (Enter to keep)"
        }
        $params = @{
            Label = $pair.Label
            AllowBlank = $true
        }
        if ($pair.Secret) { $params.Secret = $true }
        $value = Read-SettingPrompt @params
        if ($value) {
            Set-EnvValue $EnvFile $pair.Key $value
        }
    }

    Set-GarminAlertSettings
    Write-Host ""
    Write-Host "First Garmin sign-in runs in a terminal on this computer:" -ForegroundColor DarkGray
    Write-Host "  .venv\Scripts\python.exe scripts\garmin_auth.py" -ForegroundColor DarkGray
    Write-Host "You type the Garmin email, password, and verification code in that window." -ForegroundColor DarkGray
    Write-Host "The password is used only for that sign-in. It is not saved." -ForegroundColor DarkGray

    return @{
        ApiSecretKey = $apiSecret
        PublicBaseUrl = (Get-EnvValueFromFile $EnvFile "PUBLIC_BASE_URL")
    }
}

function Resolve-GarminTokenPath {
    $raw = Get-EnvValueFromFile $EnvFile "GARMIN_TOKEN_PATH"
    if (-not $raw) { $raw = Join-Path $env:USERPROFILE ".garminconnect" }
    if ($raw -eq "~") {
        $raw = $env:USERPROFILE
    } elseif ($raw -match "^~/|^~\\") {
        $raw = Join-Path $env:USERPROFILE $raw.Substring(2)
    }
    return $raw
}

function Test-GarminTokensPresent {
    $tokenPath = Resolve-GarminTokenPath
    if (-not (Test-Path $tokenPath)) { return $false }
    $item = Get-Item $tokenPath
    if ($item.PSIsContainer) {
        return (Test-Path (Join-Path $tokenPath "garmin_tokens.json"))
    }
    return $true
}

function Invoke-GarminAuthGate([string]$PythonExe) {
    if ($SkipGarminAuth) {
        Write-Host "Skipping Garmin auth gate (-SkipGarminAuth)"
        return
    }

    if (Test-GarminTokensPresent) {
        Write-Host "Garmin tokens found; skipping auth."
        return
    }

    $authScript = Join-Path $ScriptsDir "garmin_auth.py"
    $authCmd = ".venv\Scripts\python.exe scripts\garmin_auth.py"
    Write-Step "Garmin Connect authentication"

    $tokenDir = Resolve-GarminTokenPath
    $env:GARMIN_TOKEN_PATH = $tokenDir

    $shouldRun = $false
    if ($RunGarminAuth) {
        $shouldRun = $true
    } elseif ($NonInteractive -or $Repair) {
        Write-Warning "Garmin tokens missing. Run interactively:"
        Write-Host "  $authCmd" -ForegroundColor Yellow
        return
    } else {
        $answer = Read-Host "Garmin tokens not found. Run garmin_auth.py now? [Y/n]"
        if (-not $answer -or $answer -match '^(y|yes)$') {
            $shouldRun = $true
        } else {
            Write-Host "Skipped Garmin auth. Later: $authCmd"
            return
        }
    }

    if ($shouldRun) {
        Write-Host "Running $authScript ..."
        & $PythonExe $authScript
        $exit = $LASTEXITCODE
        if ($exit -ne 0) {
            if ($RunGarminAuth) {
                throw "garmin_auth.py failed with exit code $exit"
            }
            Write-Warning "garmin_auth.py exited with code $exit. Continue install; re-run: $authCmd"
        }
    }
}

function Test-CoachHealth {
    Write-Step "Verifying coach health endpoints"
    $checks = @(
        @{ Name = "API"; Url = "http://127.0.0.1:8000/health" },
        @{ Name = "MCP"; Url = "http://127.0.0.1:8080/health" }
    )
    $failed = @()
    foreach ($check in $checks) {
        try {
            $r = Invoke-WebRequest -Uri $check.Url -UseBasicParsing -TimeoutSec 10
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) {
                Write-Host "$($check.Name) health OK: $($check.Url)" -ForegroundColor Green
            } else {
                Write-Warning "$($check.Name) health unexpected status $($r.StatusCode): $($check.Url)"
                $failed += $check.Name
            }
        } catch {
            Write-Warning "$($check.Name) health failed: $($check.Url) - $($_.Exception.Message)"
            $failed += $check.Name
        }
    }
    return ($failed.Count -eq 0)
}

function Show-InstallSummary {
    param(
        [hashtable]$WizardResult,
        [bool]$DockerMode,
        [bool]$GarminTokensOk,
        [switch]$Short
    )

    $apiSecret = $WizardResult.ApiSecretKey
    if (-not $apiSecret) {
        $apiSecret = Get-EnvValueFromFile $EnvFile "API_SECRET_KEY"
    }
    $publicUrl = $WizardResult.PublicBaseUrl
    if (-not $publicUrl) {
        $publicUrl = Get-EnvValueFromFile $EnvFile "PUBLIC_BASE_URL"
    }
    if (-not $publicUrl) {
        $publicUrl = "http://127.0.0.1:8000"
    }
    $mcpUrl = "http://127.0.0.1:8080/mcp"
    try {
        $publicUri = [Uri]$publicUrl
        $loopback = @("127.0.0.1", "localhost", "::1")
        if ($publicUri.Host -and ($loopback -notcontains $publicUri.Host)) {
            $mcpUrl = $publicUrl.TrimEnd('/') + "/mcp"
        }
    } catch {}

    $modeLabel = if ($DockerMode) { "Docker (coach-active.marker)" } else { "Native (scheduled tasks)" }
    $title = if ($Repair) { "Repair complete" } else { "Installation complete" }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  $title" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Mode: $modeLabel" -ForegroundColor Cyan
    Write-Host "Health:"
    Write-Host "  API  http://127.0.0.1:8000/health"
    Write-Host "  MCP  http://127.0.0.1:8080/health"
    Write-Host "  MCP connector: $mcpUrl"
    Write-Host ""

    if (-not $Short) {
        Write-Host "Your API secret key:" -ForegroundColor Cyan
        Write-Host "  $apiSecret"
        Write-Host ""
        Write-Host "MCP connector for any assistant (copy this JSON):" -ForegroundColor Cyan
        $mcpServer = @{
            url = $mcpUrl
            transport = "streamable-http"
            headers = @{
                Authorization = "Bearer $apiSecret"
            }
        }
        $mcpJson = $mcpServer | ConvertTo-Json -Depth 4
        Write-Host $mcpJson
        $clientFile = Join-Path $InstallRoot "config\mcp-client.json"
        New-Item -ItemType Directory -Force -Path (Split-Path $clientFile) | Out-Null
        @{ mcpServers = @{ "endurance-coach" = $mcpServer } } |
            ConvertTo-Json -Depth 6 |
            Set-Content -Path $clientFile -Encoding utf8
        Write-Host "Saved the same connector to $clientFile"
        Write-Host "REST, if the assistant cannot speak MCP:"
        Write-Host "  POST $($publicUrl.TrimEnd('/'))/api/v1/coach/explain-today"
        Write-Host '  Authorization: Bearer <the API secret above>'
        Write-Host ""
    }

    Write-Host "Next steps:"
    if (-not $GarminTokensOk) {
        Write-Host "  - Garmin auth:  .venv\Scripts\python.exe scripts\garmin_auth.py"
    }
    if ($DockerMode) {
        Write-Host "  - Stack:        Docker compose (marker present; native API/MCP tasks skipped)"
    } else {
        Write-Host "  - Start now:    powershell -File scripts\restart_app_services.ps1"
    }
    Write-Host "  - Health:       http://127.0.0.1:8000/health  |  http://127.0.0.1:8080/health"
    Write-Host "  - Assistant:    paste config\mcp-client.json into any MCP client, or call the REST coach URL"
    $alertProvider = Get-EnvValueFromFile $EnvFile "GARMIN_ALERT_PROVIDER"
    if (-not $alertProvider) { $alertProvider = "ntfy" }
    if ($alertProvider -eq "none") {
        Write-Host "  - Garmin alert: off. Sign in on this computer with scripts\garmin_auth.py when the token expires."
    } else {
        Write-Host "  - Garmin alert: $alertProvider. The message opens this server's sign-in page and does not contain the Garmin password."
    }
    Write-Host ""
    Write-Host "Docs: INSTALL.md"
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

    Write-Step "Caddy + DuckDNS reverse proxy"
    Initialize-LocalJson
    $config = Get-Content $LocalJson -Raw | ConvertFrom-Json

    if (-not $NonInteractive) {
        Write-Host ""
        Write-Host "Caddy reverse proxy settings (Enter to keep defaults / skip optional fields)" -ForegroundColor Yellow
        $caddyRootDefault = if ($config.caddy_root) { $config.caddy_root } else { "C:\Caddy" }
        $caddyRoot = Read-SettingPrompt -Label "Caddy install directory" -Default $caddyRootDefault
        if ($caddyRoot) { $config.caddy_root = $caddyRoot }
        $config.duckdns_token = Read-SettingPrompt -Label "DuckDNS token" -AllowBlank -Secret
        $config.duckdns_domain = Read-SettingPrompt -Label "DuckDNS domain (e.g. yourname)" -AllowBlank
        $config.lan_bind_ip = Read-SettingPrompt -Label "LAN bind IP for Caddy (e.g. 192.168.1.10)" -AllowBlank
        $wanDefault = if ($config.wan_adapter_name) { $config.wan_adapter_name } else { "Ethernet" }
        $wan = Read-SettingPrompt -Label "WAN adapter name for DuckDNS updater" -Default $wanDefault
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

function Ensure-DockerModeMarker {
    if ($Docker -and -not (Test-Path $DockerMarker)) {
        $note = "Created by Install-EnduranceCoach.ps1 -Docker at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        Set-Content -Path $DockerMarker -Value $note -Encoding utf8
        Write-Host "Created Docker mode marker: $DockerMarker"
    }
}

function Invoke-DockerStackRecovery {
    param([string]$Reason = "installer")

    if (-not (Test-Path $CoachStackHelpers)) {
        throw "Missing coach stack helpers: $CoachStackHelpers"
    }
    Write-Step "Docker stack recovery ($Reason)"
    . $CoachStackHelpers
    $ok = Invoke-CoachDockerRecovery -Reason $Reason -StartupWaitSec 45
    if (-not $ok) {
        throw "Docker stack recovery failed ($Reason). Check logs\coach-docker.log"
    }
    return $true
}

# --- Main -------------------------------------------------------------------

Write-Host "Endurance Coach installer"
if ($Repair) { Write-Host "Mode: Repair" -ForegroundColor Yellow }
if ($Docker) { Write-Host "Mode: Docker requested" -ForegroundColor Yellow }
Write-Host "Install root: $InstallRoot"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Ensure-DockerModeMarker
$DockerMode = $Docker -or (Test-Path $DockerMarker)
if ($DockerMode) {
    Write-Host "Docker mode active (marker: $DockerMarker)"
}

$python = Ensure-Python

$wizardResult = @{
    ApiSecretKey  = $null
    PublicBaseUrl = $null
}

if ($Repair) {
    if (-not (Test-Path $EnvFile)) {
        $wizardResult = Initialize-EnvFile
    } else {
        Write-Step "Repair: skipping interactive wizard (.env present)"
        $wizardResult = @{
            ApiSecretKey  = Get-EnvValueFromFile $EnvFile "API_SECRET_KEY"
            PublicBaseUrl = Get-EnvValueFromFile $EnvFile "PUBLIC_BASE_URL"
        }
    }
    Ensure-McpEnvDefaults
} else {
    $wizardResult = Initialize-EnvFile
    Ensure-McpEnvDefaults
}

Install-PythonDependencies $python
Invoke-GarminAuthGate $python

if ($NonInteractive -or $Repair) {
    Write-Step "Ensuring API secret"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ScriptsDir "generate_api_secret.ps1")
    $wizardResult.ApiSecretKey = Get-EnvValueFromFile $EnvFile "API_SECRET_KEY"
    $wizardResult.PublicBaseUrl = Get-EnvValueFromFile $EnvFile "PUBLIC_BASE_URL"
}

$dockerRecoveryFailed = $false
if ($DockerMode) {
    try {
        Invoke-DockerStackRecovery -Reason "installer"
    } catch {
        $dockerRecoveryFailed = $true
        if ($Repair -or $Docker) {
            throw
        }
        Write-Warning $_.Exception.Message
    }
} else {
    Wait-ForPostgres
}

try {
    Invoke-Migrations $python
} catch {
    Write-Warning "Migrations failed: $($_.Exception.Message). Fix PostgreSQL and rerun alembic upgrade head."
}

Install-ScheduledTasks

if ($DockerMode -and -not $dockerRecoveryFailed) {
    # Second pass after tasks/migrations (idempotent; Repair flow step)
    try {
        Invoke-DockerStackRecovery -Reason "installer-post-migrate"
    } catch {
        $dockerRecoveryFailed = $true
        if ($Repair -or $Docker) {
            throw
        }
        Write-Warning $_.Exception.Message
    }
}

if ($WithCaddy) {
    Install-CaddyOptional
}

$healthOk = Test-CoachHealth
if (-not $healthOk) {
    if ($Repair -or $dockerRecoveryFailed) {
        throw "Health checks failed. Repair/Docker recovery requires healthy API (8000) and MCP (8080)."
    }
    Write-Warning "Health checks failed; install continued. Start services and re-check /health endpoints."
}

$garminOk = Test-GarminTokensPresent
Show-InstallSummary -WizardResult $wizardResult -DockerMode:$DockerMode -GarminTokensOk:$garminOk -Short:$Repair
