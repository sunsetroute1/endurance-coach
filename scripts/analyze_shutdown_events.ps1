# Summarize recent shutdown, reboot, crash, and power-loss events from Windows logs.
param(
    [int]$Days = 30
)

$ErrorActionPreference = 'Continue'
$since = (Get-Date).AddDays(-$Days)

function Get-EventsSafe {
    param(
        [string]$LogName,
        [int[]]$Ids,
        [datetime]$StartTime
    )
    try {
        return @(Get-WinEvent -FilterHashtable @{
            LogName   = $LogName
            Id        = $Ids
            StartTime = $StartTime
        } -ErrorAction Stop)
    } catch {
        return @()
    }
}

function FirstLine([string]$Message) {
    if (-not $Message) { return '' }
    $line = ($Message -split "`r?`n")[0]
    if ($line.Length -gt 220) { return $line.Substring(0, 217) + '...' }
    return $line
}

function Interpret-ShutdownEvent {
    param($Event)
    switch ($Event.Id) {
        41 { return 'Unexpected shutdown / power loss (Kernel-Power)' }
        6008 { return 'Previous shutdown was unexpected' }
        1074 { return 'Clean shutdown or restart initiated' }
        6006 { return 'Event log service stopped (normal shutdown path)' }
        109 { return 'Kernel init: boot after shutdown' }
        6005 { return 'Event log service started (system boot)' }
        6009 { return 'Microsoft Windows version at boot' }
        1100 { return 'Security log service stopped' }
        1101 { return 'Audit service shutdown notification' }
        1001 { return 'Bugcheck / blue screen recorded' }
        7031 { return 'Service terminated unexpectedly and was restarted' }
        7034 { return 'Service terminated unexpectedly' }
        7023 { return 'Service terminated with error' }
        7026 { return 'Boot-start driver failed to load' }
        6013 { return 'System uptime at event time' }
        default { return "Event ID $($Event.Id)" }
    }
}

Write-Host "=== Shutdown / reboot analysis (last $Days days) ===" -ForegroundColor Cyan
Write-Host "Since: $($since.ToString('yyyy-MM-dd HH:mm:ss'))"
Write-Host ""

$systemIds = @(41, 1074, 6006, 6008, 109, 6005, 6009, 6013, 7031, 7034, 7023, 7026)
$appIds = @(1001, 1002)

$systemEvents = Get-EventsSafe -LogName 'System' -Ids $systemIds -StartTime $since
$appEvents = Get-EventsSafe -LogName 'Application' -Ids $appIds -StartTime $since
$all = @($systemEvents + $appEvents) | Sort-Object TimeCreated -Descending

if ($all.Count -eq 0) {
    Write-Host 'No matching shutdown/reboot events found in the requested window.' -ForegroundColor Yellow
    exit 0
}

Write-Host 'Recent events (newest first):' -ForegroundColor Cyan
$all | Select-Object -First 35 | ForEach-Object {
    $kind = Interpret-ShutdownEvent $_
    Write-Host ("[{0:yyyy-MM-dd HH:mm:ss}] ID {1} ({2})" -f $_.TimeCreated, $_.Id, $_.ProviderName)
    Write-Host ("  {0}" -f $kind)
    Write-Host ("  {0}" -f (FirstLine $_.Message))
    Write-Host ''
}

$unexpected = @($all | Where-Object { $_.Id -in 41, 6008, 1001 })
$clean = @($all | Where-Object { $_.Id -eq 1074 })
$boots = @($all | Where-Object { $_.Id -in 6005, 109 })

Write-Host '=== Summary ===' -ForegroundColor Cyan
Write-Host ("Unexpected shutdown / bugcheck / power-loss markers: {0}" -f $unexpected.Count)
Write-Host ("Clean initiated shutdown/restart events (1074): {0}" -f $clean.Count)
Write-Host ("Boot markers (6005/109): {0}" -f $boots.Count)
Write-Host ''

if ($unexpected.Count -gt 0) {
    Write-Host 'Most likely causes from event pattern:' -ForegroundColor Yellow
    $has41 = @($unexpected | Where-Object { $_.Id -eq 41 }).Count
    $has6008 = @($unexpected | Where-Object { $_.Id -eq 6008 }).Count
    $hasBugcheck = @($unexpected | Where-Object { $_.Id -eq 1001 }).Count
    if ($has41 -gt 0 -or $has6008 -gt 0) {
        Write-Host '  - Sudden power loss, hard reset, crash before shutdown logging, or PSU issue'
    }
    if ($hasBugcheck -gt 0) {
        Write-Host '  - Blue screen / bugcheck (see Application log 1001 details above)'
    }
}

if ($clean.Count -gt 0) {
    Write-Host ''
    Write-Host 'Recent intentional shutdown/restart reasons (1074):' -ForegroundColor Green
    $clean | Select-Object -First 8 | ForEach-Object {
        Write-Host ("  [{0:yyyy-MM-dd HH:mm:ss}] {1}" -f $_.TimeCreated, (FirstLine $_.Message))
    }
}

# Reliability history if available
Write-Host ''
Write-Host '=== Reliability Monitor hint ===' -ForegroundColor Cyan
Write-Host 'Open: perfmon /rel'
Write-Host 'Look for red X (failures) on dates matching the unexpected events above.'
