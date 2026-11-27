# Sync Garmin data and run process + analytics pipeline.
# Usage:
#   powershell -File sync_garmin_pipeline.ps1
#   powershell -File sync_garmin_pipeline.ps1 -RecentDays 3
#   powershell -File sync_garmin_pipeline.ps1 -FullSync
#   powershell -File sync_garmin_pipeline.ps1 -WaitForMorningReadiness
param(
    [switch]$FullSync,
    [switch]$WaitForMorningReadiness,
    [string]$ApiBase = "http://localhost:8000",
    [string]$Since,
    # Scheduled runs pass 3. That limits each Garmin pull to the last 3 days
    # after the first successful run of the local day, which still uses the
    # server default (30 days). Omit this for a manual 30-day sync.
    [int]$RecentDays = 0,
    [int]$MorningPollMinutes = 1,
    [int]$MorningPollMaxAttempts = 2
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "sync-pipeline.log"
$StatusFile = Join-Path $LogDir "morning-readiness-status.json"
$WindowStamp = Join-Path $LogDir "garmin-daily-window.date"
$AuthPauseFile = Join-Path $env:USERPROFILE ".endurance-coach\garmin-auth.paused"
$AuthRetryFile = Join-Path $env:USERPROFILE ".endurance-coach\garmin-auth.retry"
$AuthRetryHours = 1
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    $line | Out-File -FilePath $LogFile -Append -Encoding utf8
}

function Test-InMorningSyncWindow {
    # After manual Garmin Connect sync (~7-9 AM), poll only until the 9:01 AM cutoff.
    $now = Get-Date
    return ($now.Hour -eq 9 -and $now.Minute -le 1)
}

function Invoke-ApiPost([string]$Path, [hashtable]$Body) {
    $json = $Body | ConvertTo-Json -Compress
    $headers = @{}
    if ($script:ApiSecretKey) {
        $headers["Authorization"] = "Bearer $script:ApiSecretKey"
    }
    return Invoke-RestMethod -Method POST -Uri "$ApiBase$Path" -ContentType "application/json" -Headers $headers -Body $json
}

function Invoke-ApiGet([string]$Path) {
    $headers = @{}
    if ($script:ApiSecretKey) {
        $headers["Authorization"] = "Bearer $script:ApiSecretKey"
    }
    return Invoke-RestMethod -Method GET -Uri "$ApiBase$Path" -Headers $headers
}

function Save-MorningReadinessStatus($Status) {
    $Status | ConvertTo-Json -Depth 6 | Out-File -FilePath $StatusFile -Encoding utf8
}

function Test-StaleGarminAuth([string]$Text) {
    return $Text -match '(?i)(\b401\b|\b429\b|unauthorized|social profile|tokens expired|authentication failed|too many login|rate limit|automatic sync is paused)'
}

function New-GarminPhoneLoginLink {
    if (-not $script:PublicBaseUrl) { return $null }
    $dir = Join-Path $env:USERPROFILE ".endurance-coach"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $token = [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
    $expires = [datetimeoffset]::UtcNow.AddHours(12).ToString("o")
    $json = '{"token":"' + $token + '","expires_at":"' + $expires + '"}'
    $path = Join-Path $dir "garmin-login-grant.json"
    [System.IO.File]::WriteAllText($path, $json)
    return "$($script:PublicBaseUrl)/api/v1/garmin/login?t=$token"
}

function New-GarminAlertSummary([bool]$HasLink) {
    if ($HasLink) {
        return "Garmin rejected the saved login on this server. The link opens the sign-in page hosted on this server, because Garmin sign-in has to run on this computer. Type your Garmin email, password, and verification code on that page. The password is used only for that sign-in. It is not saved, and this alert does not contain it. Leave the server VPN off until the page says you are signed in."
    }
    return "Garmin rejected the saved login. Sign-in has to run on this server. On this computer, run python scripts/garmin_auth.py and type the Garmin email, password, and verification code there. The password is used only for that sign-in. It is not saved, and this alert does not contain it."
}

function Get-GarminAlertProviders {
    $raw = $script:AlertProvider
    if ($raw) {
        return @($raw.Split(",") | ForEach-Object { $_.Trim().ToLower() } | Where-Object { $_ -and $_ -ne "none" })
    }
    if ($script:NtfyTopic) { return @("ntfy") }
    return @()
}

function Send-GarminAlertNtfy([string]$Summary, [string]$Link) {
    $topic = $script:NtfyTopic
    if (-not $topic) {
        Write-Log "Garmin ntfy alert skipped: no topic."
        return $false
    }
    if ($topic -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$') {
        Write-Log "Garmin ntfy alert skipped: topic must be one name, not a URL."
        return $false
    }
    $server = $script:NtfyServer
    if (-not $server) { $server = "https://ntfy.sh" }
    $server = $server.TrimEnd("/")
    $headers = @{
        Title = "Endurance Coach: Garmin login failed"
        Priority = "high"
        Tags = "warning"
    }
    if ($Link) {
        $headers["Click"] = $Link
        $headers["Actions"] = "view, Sign in, $Link"
    }
    if ($script:NtfyToken) {
        $headers["Authorization"] = "Bearer $($script:NtfyToken)"
        $headers["Email"] = "yes"
    }
    Invoke-RestMethod -Method POST -Uri "$server/$topic" -Body $Summary -ContentType "text/plain; charset=utf-8" -Headers $headers -TimeoutSec 20 | Out-Null
    Write-Log "Sent Garmin auth alert via ntfy."
    return $true
}

function Send-GarminAlertEmail([string]$Summary, [string]$Link) {
    $smtpHost = $script:AlertSmtpHost
    $to = $script:AlertEmailTo
    if (-not $smtpHost -or -not $to) {
        Write-Log "Garmin email alert skipped: SMTP host or recipient is empty."
        return $false
    }
    $from = $script:AlertSmtpFrom
    if (-not $from) { $from = $script:AlertSmtpUser }
    if (-not $from) {
        Write-Log "Garmin email alert skipped: no From address."
        return $false
    }
    $port = 587
    if ($script:AlertSmtpPort -match '^\d+$') { $port = [int]$script:AlertSmtpPort }
    $body = $Summary
    if ($Link) { $body = $Summary + "`r`n`r`n" + $Link }
    $message = New-Object System.Net.Mail.MailMessage($from, $to, "Endurance Coach: Garmin login failed", $body)
    $client = New-Object System.Net.Mail.SmtpClient($smtpHost, $port)
    $client.EnableSsl = ($port -ne 25)
    $client.Timeout = 20000
    if ($script:AlertSmtpUser) {
        $client.Credentials = New-Object System.Net.NetworkCredential($script:AlertSmtpUser, $script:AlertSmtpPassword)
    }
    try {
        $client.Send($message)
    } finally {
        $message.Dispose()
        $client.Dispose()
    }
    Write-Log "Sent Garmin auth alert via email."
    return $true
}

function Send-GarminAlertWebhook([string]$Summary, [string]$Link) {
    $url = $script:AlertWebhookUrl
    if (-not $url) {
        Write-Log "Garmin webhook alert skipped: no URL."
        return $false
    }
    $safeLink = if ($Link) { $Link } else { "" }
    $headers = @{}
    if ($script:AlertWebhookHeader -match '^([^:]+):\s*(.+)$') {
        $headers[$Matches[1].Trim()] = $Matches[2].Trim()
    }
    if ($script:AlertWebhookBody) {
        $body = $script:AlertWebhookBody.Replace("{message}", $Summary).Replace("{link}", $safeLink)
        $contentType = $script:AlertWebhookContentType
        if (-not $contentType) {
            $contentType = "application/x-www-form-urlencoded"
        }
    } else {
        $body = @{
            title = "Endurance Coach: Garmin login failed"
            message = $Summary
            link = $safeLink
        } | ConvertTo-Json -Compress
        $contentType = "application/json"
    }
    Invoke-RestMethod -Method POST -Uri $url -Body $body -ContentType $contentType -Headers $headers -TimeoutSec 20 | Out-Null
    Write-Log "Sent Garmin auth alert via webhook."
    return $true
}

function Send-GarminAuthAlert([string]$Reason) {
    $providers = @(Get-GarminAlertProviders)
    if ($providers.Count -eq 0) { return $false }
    $link = New-GarminPhoneLoginLink
    $summary = New-GarminAlertSummary -HasLink ([bool]$link)
    $sent = $false
    foreach ($provider in $providers) {
        try {
            $ok = $false
            switch ($provider) {
                "ntfy" { $ok = Send-GarminAlertNtfy -Summary $summary -Link $link }
                "email" { $ok = Send-GarminAlertEmail -Summary $summary -Link $link }
                "webhook" { $ok = Send-GarminAlertWebhook -Summary $summary -Link $link }
                "sms" { $ok = Send-GarminAlertWebhook -Summary $summary -Link $link }
                default { Write-Log "Garmin alert provider '$provider' is not supported." }
            }
            if ($ok) { $sent = $true }
        } catch {
            Write-Log "Garmin auth alert via $provider failed: $($_.Exception.Message)"
        }
    }
    return $sent
}

function Read-GarminAuthRetry {
    $state = @{ LastAttempt = $null; Alerted = $false }
    if (-not (Test-Path $AuthRetryFile)) { return $state }
    foreach ($line in Get-Content $AuthRetryFile) {
        if ($line -match '^last_attempt=(.+)$') {
            $stamp = $Matches[1].Trim()
            if ($stamp) {
                try { $state.LastAttempt = [datetimeoffset]::Parse($stamp).LocalDateTime } catch {}
            }
        } elseif ($line -match '^alerted=(.+)$') {
            $state.Alerted = $Matches[1].Trim() -eq "1"
        }
    }
    return $state
}

function Write-GarminAuthRetry($State) {
    $dir = Split-Path $AuthRetryFile -Parent
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $stamp = ""
    if ($State.LastAttempt) {
        $stamp = ([datetimeoffset]$State.LastAttempt).ToString("o")
    }
    $alerted = if ($State.Alerted) { "1" } else { "0" }
    [System.IO.File]::WriteAllText($AuthRetryFile, "last_attempt=$stamp`r`nalerted=$alerted`r`n")
}

function Clear-GarminAuthRetry {
    if (Test-Path $AuthRetryFile) {
        Remove-Item $AuthRetryFile -Force
    }
}

function Set-GarminAuthPause([string]$Reason) {
    $dir = Split-Path $AuthPauseFile -Parent
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    [System.IO.File]::WriteAllText($AuthPauseFile, $Reason.Trim() + [Environment]::NewLine)
    $state = Read-GarminAuthRetry
    $state.LastAttempt = Get-Date
    if (-not $state.Alerted) {
        if (Send-GarminAuthAlert $Reason) { $state.Alerted = $true }
    }
    Write-GarminAuthRetry $state
    $next = $state.LastAttempt.AddHours($AuthRetryHours).ToString("o")
    Write-Log "Garmin auth is failing. Next retry at $next. $Reason"
}

function New-SyncBody {
    $syncBody = @{}
    if ($FullSync) { $syncBody.full_sync = $true }
    if ($Since) {
        $syncBody.since = $Since
        return $syncBody
    }
    if ($RecentDays -gt 0) {
        $today = (Get-Date).ToString("yyyy-MM-dd")
        $lastWindow = ""
        if (Test-Path $WindowStamp) {
            $lastWindow = (Get-Content -Path $WindowStamp -Raw).Trim()
        }
        if ($lastWindow -eq $today) {
            $start = (Get-Date).Date.AddDays(-($RecentDays - 1))
            $syncBody.since = $start.ToString("yyyy-MM-ddTHH:mm:ss")
        }
    }
    return $syncBody
}

function Invoke-SyncPipelineCore() {
    $syncBody = New-SyncBody
    $dailyWindow = ($RecentDays -gt 0 -and -not $Since -and -not $FullSync -and -not $syncBody.ContainsKey("since"))
    $sinceLabel = if ($syncBody.ContainsKey("since")) { $syncBody.since } else { "" }

    Write-Log "Starting Garmin sync (full_sync=$($FullSync.IsPresent), since=$sinceLabel, daily_window=$dailyWindow)..."
    $sync = Invoke-ApiPost "/api/v1/sync/garmin" $syncBody
    Write-Log ("Sync status: {0} synced={1}" -f $sync.status, ($sync.resources_synced | ConvertTo-Json -Compress))

    Write-Log "Processing normalized records..."
    $processLimit = if ($FullSync -or $dailyWindow) { 500 } else { 100 }
    $process = Invoke-ApiPost "/api/v1/process" @{ limit = $processLimit }
    Write-Log ("Processed: {0}" -f ($process.processed | ConvertTo-Json -Compress))

    Write-Log "Computing analytics..."
    $analytics = Invoke-ApiPost "/api/v1/analytics/compute" @{}
    Write-Log ("Analytics families: {0}" -f ($analytics.families -join ", "))

    if ($dailyWindow) {
        Set-Content -Path $WindowStamp -Value (Get-Date).ToString("yyyy-MM-dd") -Encoding ascii
    }
}

function Get-MorningReadinessStatus() {
    return Invoke-ApiGet "/api/v1/garmin/morning-readiness-status"
}

$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match '^\s*API_SECRET_KEY=(.+)$') {
            $script:ApiSecretKey = $Matches[1].Trim()
        } elseif ($line -match '^\s*GARMIN_ALERT_PROVIDER=(.+)$') {
            $script:AlertProvider = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_NTFY_TOPIC=(.+)$') {
            $script:NtfyTopic = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_NTFY_TOKEN=(.+)$') {
            $script:NtfyToken = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_NTFY_SERVER=(.+)$') {
            $script:NtfyServer = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_EMAIL_TO=(.+)$') {
            $script:AlertEmailTo = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_SMTP_HOST=(.+)$') {
            $script:AlertSmtpHost = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_SMTP_PORT=(.+)$') {
            $script:AlertSmtpPort = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_SMTP_USER=(.+)$') {
            $script:AlertSmtpUser = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_SMTP_PASSWORD=(.+)$') {
            $script:AlertSmtpPassword = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_SMTP_FROM=(.+)$') {
            $script:AlertSmtpFrom = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_WEBHOOK_URL=(.+)$') {
            $script:AlertWebhookUrl = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_WEBHOOK_HEADER=(.+)$') {
            $script:AlertWebhookHeader = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_WEBHOOK_BODY=(.+)$') {
            $script:AlertWebhookBody = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*GARMIN_ALERT_WEBHOOK_CONTENT_TYPE=(.+)$') {
            $script:AlertWebhookContentType = $Matches[1].Trim().Trim('"').Trim("'")
        } elseif ($line -match '^\s*PUBLIC_BASE_URL=(.+)$') {
            $script:PublicBaseUrl = $Matches[1].Trim().Trim('"').Trim("'").TrimEnd("/")
        }
    }
}

try {
    if (Test-Path $AuthPauseFile) {
        $reason = (Get-Content -Path $AuthPauseFile -Raw).Trim()
        $state = Read-GarminAuthRetry
        $elapsed = $null
        if ($state.LastAttempt) { $elapsed = (Get-Date) - $state.LastAttempt }
        if ($elapsed -and $elapsed.TotalHours -lt $AuthRetryHours) {
            $next = $state.LastAttempt.AddHours($AuthRetryHours).ToString("o")
            Write-Log "Skipping Garmin sync; auth is failing. Next retry at $next. $reason"
            exit 0
        }
        Write-Log "Retrying Garmin sync after auth failure."
        Remove-Item $AuthPauseFile -Force
        $state.LastAttempt = Get-Date
        Write-GarminAuthRetry $state
    }

    Invoke-SyncPipelineCore

    $status = Get-MorningReadinessStatus
    Save-MorningReadinessStatus $status
    Write-Log ("Morning readiness: status={0} missing={1} last_successful_metric_timestamp={2}" -f `
        $status.status, ($status.missing_fields -join ","), $status.last_successful_metric_timestamp)

    $shouldWait = $WaitForMorningReadiness.IsPresent -or (Test-InMorningSyncWindow)
    if ($shouldWait -and $status.status -eq "partial") {
        Write-Log ("Morning readiness incomplete; polling every {0} min up to {1} attempts (9:01 AM cutoff)" -f `
            $MorningPollMinutes, $MorningPollMaxAttempts)
        for ($attempt = 1; $attempt -le $MorningPollMaxAttempts; $attempt++) {
            if (-not (Test-InMorningSyncWindow)) {
                Write-Log "Past 9:01 AM morning sync window; stopping polls."
                break
            }
            Start-Sleep -Seconds ($MorningPollMinutes * 60)
            if (-not (Test-InMorningSyncWindow)) {
                Write-Log "Reached 9:01 AM cutoff during poll wait; stopping."
                break
            }
            Write-Log "Morning readiness poll attempt $attempt/$MorningPollMaxAttempts"
            Invoke-SyncPipelineCore
            $status = Get-MorningReadinessStatus
            Save-MorningReadinessStatus $status
            Write-Log ("Morning readiness: status={0} missing={1}" -f `
                $status.status, ($status.missing_fields -join ","))
            if ($status.status -eq "complete") {
                Write-Log "Morning readiness complete; workflow may proceed."
                break
            }
        }
        if ($status.status -ne "complete") {
            Clear-GarminAuthRetry
            Write-Log "Morning readiness still partial after 9:01 AM window; sending nothing."
            exit 2
        }
    } elseif ($status.status -eq "partial") {
        Write-Log "Morning readiness partial outside 9:00-9:01 AM window; sync succeeded, readiness still partial."
    }

    Clear-GarminAuthRetry
    Write-Log "Pipeline complete."
    exit 0
} catch {
    $detail = $_.Exception.Message
    if ($_.ErrorDetails.Message) { $detail = "$detail $($_.ErrorDetails.Message)" }
    Write-Log "ERROR: $detail"
    if (Test-StaleGarminAuth $detail) {
        Set-GarminAuthPause $detail
    }
    exit 1
}
