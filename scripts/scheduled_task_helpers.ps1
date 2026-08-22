# Shared helpers for hidden scheduled-task and child process launches.

function Get-HiddenLauncherDirectory {
    'C:\ProgramData\silent-launchers'
}

function New-HiddenLauncherVbs {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TargetPath,
        [string[]]$TargetArgs = @(),
        [ValidateSet('powershell', 'cmd', 'exe')]
        [string]$TargetType = 'powershell',
        [string]$WorkingDirectory = ''
    )

    $launcherDir = Get-HiddenLauncherDirectory
    New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null

    $keySource = "$TargetType|$TargetPath|$WorkingDirectory|$($TargetArgs -join '|')"
    $hash = [Math]::Abs($keySource.GetHashCode())
    $vbsPath = Join-Path $launcherDir ("launcher_{0}.vbs" -f $hash)

    $escapedTarget = $TargetPath -replace '"', '""'
    $escapedWorkDir = $WorkingDirectory -replace '"', '""'

    switch ($TargetType) {
        'powershell' {
            $command = "-NoProfile -ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File ""$escapedTarget"""
            if ($TargetArgs.Count -gt 0) {
                $command += ' ' + ($TargetArgs -join ' ')
            }
            $runTarget = "powershell.exe $command"
        }
        'cmd' {
            $runTarget = "cmd.exe /c ""$escapedTarget"""
        }
        default {
            $argSuffix = if ($TargetArgs.Count -gt 0) { ' ' + ($TargetArgs -join ' ') } else { '' }
            $runTarget = """$escapedTarget""$argSuffix"
        }
    }

    if ($WorkingDirectory) {
        $vbs = @"
Set shell = CreateObject("Wscript.Shell")
shell.CurrentDirectory = "$escapedWorkDir"
shell.Run "$($runTarget -replace '"', '""')", 0, False
"@
    } else {
        $vbs = @"
CreateObject("Wscript.Shell").Run "$($runTarget -replace '"', '""')", 0, False
"@
    }

    Set-Content -Path $vbsPath -Value $vbs -Encoding ASCII
    return $vbsPath
}

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

    $vbs = New-HiddenLauncherVbs -TargetPath $ScriptPath -TargetArgs $ScriptArgs -TargetType 'powershell'
    return New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "//B `"$vbs`""
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

    $vbs = New-HiddenLauncherVbs -TargetPath $ScriptPath -TargetArgs $ScriptArgs -TargetType 'powershell'
    $params = @{
        FilePath = 'wscript.exe'
        ArgumentList = @('//B', $vbs)
        WindowStyle = 'Hidden'
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

function Start-HiddenProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @(),
        [string]$WorkingDirectory = '',
        [ValidateSet('powershell', 'cmd', 'exe')]
        [string]$TargetType = 'exe'
    )

    $vbs = New-HiddenLauncherVbs -TargetPath $FilePath -TargetArgs $ArgumentList -TargetType $TargetType -WorkingDirectory $WorkingDirectory
    Start-Process -FilePath 'wscript.exe' -ArgumentList @('//B', $vbs) -WindowStyle Hidden | Out-Null
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
