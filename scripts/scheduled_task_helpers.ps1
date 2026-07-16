# Shared helpers for hidden/minimized scheduled-task and child PowerShell launches.

function Get-SilentPowerShellArgumentString {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,
        [string[]]$ScriptArgs = @()
    )

    $quotedScript = '"' + $ScriptPath + '"'
    $argumentString = "-NoProfile -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File $quotedScript"
    if ($ScriptArgs.Count -gt 0) {
        $argumentString += " " + ($ScriptArgs -join " ")
    }
    return $argumentString
}

function New-SilentPowerShellTaskAction {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,
        [string[]]$ScriptArgs = @()
    )

    return New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument (Get-SilentPowerShellArgumentString -ScriptPath $ScriptPath -ScriptArgs $ScriptArgs)
}

function New-SilentScheduledTaskSettings {
    param(
        [int]$RestartCount = 0,
        [TimeSpan]$RestartInterval = [TimeSpan]::FromMinutes(1),
        [TimeSpan]$ExecutionTimeLimit = [TimeSpan]::Zero,
        [string]$MultipleInstances = "IgnoreNew"
    )

    $params = @{
        AllowStartIfOnBatteries = $true
        DontStopIfGoingOnBatteries = $true
        StartWhenAvailable = $true
        Hidden = $true
    }

    if ($RestartCount -gt 0) {
        $params.RestartCount = $RestartCount
        $params.RestartInterval = $RestartInterval
    }

    if ($ExecutionTimeLimit -gt [TimeSpan]::Zero) {
        $params.ExecutionTimeLimit = $ExecutionTimeLimit
    }

    if ($MultipleInstances) {
        $params.MultipleInstances = $MultipleInstances
    }

    return New-ScheduledTaskSettingsSet @params
}

function Invoke-SilentPowerShell {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ScriptPath,
        [string[]]$ScriptArgs = @(),
        [switch]$Wait
    )

    $argumentList = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-NonInteractive",
        "-WindowStyle", "Hidden",
        "-File", $ScriptPath
    ) + $ScriptArgs

    $params = @{
        FilePath = "powershell.exe"
        ArgumentList = $argumentList
        WindowStyle = "Hidden"
        PassThru = $true
    }
    if ($Wait) {
        $params.Wait = $true
    }

    $proc = Start-Process @params
    if ($Wait -and $proc) {
        $global:LASTEXITCODE = $proc.ExitCode
        return $proc.ExitCode
    }
}

function Set-ScheduledTaskHidden {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TaskName
    )

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $settings = $task.Settings
    if ($settings.Hidden) {
        return $false
    }

    $settings.Hidden = $true
    Set-ScheduledTask -TaskName $TaskName -Settings $settings | Out-Null
    return $true
}
