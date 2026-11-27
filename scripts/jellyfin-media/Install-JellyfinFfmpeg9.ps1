#Requires -Version 5.1
<#
.SYNOPSIS
  Jellyfin FFmpeg 9 program — install, configure, repair, and verify upstream FFmpeg on Windows.

.DESCRIPTION
  One program that:
    1. Deploys runtime scripts to C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9
    2. Downloads FFmpeg 9 (gyan.dev) to C:\FFmpeg9
    3. Detects CPU/GPU and optionally auto-tunes Jellyfin encoding.xml
    4. Restarts Jellyfin and verifies health

  Use -ManualConfig to set only the FFmpeg path and leave Dashboard settings alone.
  Use -AutoTune to force hardware-based tuning without prompting.
  Default Install prompts: auto-tune vs manual/default.

.PARAMETER Action
  Install | Repair | Test | Deploy

.PARAMETER AutoTune
  Force hardware-based encoding.xml tuning.

.PARAMETER ManualConfig
  Only set EncoderAppPath; do not change other Jellyfin transcoding settings.

.PARAMETER Interactive
  Prompt for auto-tune vs manual on Install (default when running interactively).

.EXAMPLE
  .\Install-JellyfinFfmpeg9.ps1 -ManualConfig
  Install FFmpeg 9 and set EncoderAppPath only; keep Dashboard transcoding settings.

.EXAMPLE
  .\Install-JellyfinFfmpeg9.ps1 -AutoTune
  Install with hardware auto-tune (no prompt).

.EXAMPLE
  .\Install-JellyfinFfmpeg9.ps1 -Action Repair
  Idempotent fix after Jellyfin update (Watchboard Fix uses this).

.EXAMPLE
  .\Install-JellyfinFfmpeg9.ps1 -Action Test -Json
  Health check JSON for Automation Watchboard.
#>
[CmdletBinding()]
param(
    [ValidateSet('Install', 'Repair', 'Test', 'Deploy')]
    [string]$Action = 'Install',
    [string]$FfmpegRoot = 'C:\FFmpeg9',
    [string]$ProgramRoot = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9',
    [switch]$SkipDeploy,
    [switch]$SkipFfmpegDownload,
    [switch]$AutoTune,
    [switch]$ManualConfig,
    [switch]$Interactive = $true,
    [switch]$Json,
    [switch]$Elevated
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = 'C:\ProgramData\Jellyfin\logs'
$LogFile = Join-Path $LogDir 'jellyfin-ffmpeg9-install.log'

function Invoke-ElevatedSelf {
    $argList = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"' + $PSCommandPath + '"'),
        '-Action', $Action,
        '-FfmpegRoot', $FfmpegRoot,
        '-ProgramRoot', $ProgramRoot,
        '-Elevated'
    )
    if ($SkipDeploy) { $argList += '-SkipDeploy' }
    if ($SkipFfmpegDownload) { $argList += '-SkipFfmpegDownload' }
    if ($AutoTune) { $argList += '-AutoTune' }
    if ($ManualConfig) { $argList += '-ManualConfig' }
    if ($Interactive) { $argList += '-Interactive' }
    if ($Json) { $argList += '-Json' }
    Start-Process -FilePath (Get-Command powershell.exe).Source -Verb RunAs -ArgumentList ($argList -join ' ') | Out-Null
}

function Invoke-DeployProgram {
    param(
        [string]$SourceRoot,
        [string]$TargetRoot
    )

    $deployScript = Join-Path $SourceRoot 'installer\Deploy-JellyfinFfmpeg9.ps1'
    if (-not (Test-Path $deployScript)) {
        throw "Missing deploy script: $deployScript"
    }

    & $deployScript -SourceRoot $SourceRoot -TargetRoot $TargetRoot
}

function Invoke-RepairJellyfinFfmpeg9 {
    param(
        [string]$FfmpegPath,
        [string]$LogFile,
        [string]$ProgramRoot,
        [string]$ProfileMode,
        [ValidateSet('Install', 'Repair', 'Test', 'Deploy')]
        [string]$RepairAction = 'Repair',
        [switch]$AllowDownload,
        [switch]$Quiet
    )

    $result = [ordered]@{
        changed = $false
        actions = @()
        profile_mode = $ProfileMode
        before = $null
        after = $null
    }

    $savedConfig = Get-ProgramUserConfig -ProgramRoot $ProgramRoot
    $patchConfigured = Test-JellyfinFfmpeg9PatchConfigured -FfmpegPath $FfmpegPath -ProgramRoot $ProgramRoot
    $hardware = Get-SystemMediaHardware
    $encoderCaps = Get-FfmpegEncoderCapabilities -FfmpegPath $FfmpegPath
    $plan = if ($ProfileMode -eq 'auto') {
        Select-JellyfinHardwareAcceleration -Hardware $hardware -EncoderCaps $encoderCaps
    } else { $null }

    $result.before = Get-JellyfinFfmpeg9Status -FfmpegPath $FfmpegPath -ProgramRoot $ProgramRoot
    Write-LogLine -Message ("Action start [{0}/{1}]: {2}" -f $RepairAction, $ProfileMode, ($result.before.issues -join ', ')) -LogFile $LogFile

    if ($AllowDownload -and (
            ($result.before.issues -contains 'ffmpeg9_missing') -or
            ($result.before.issues -contains 'ffmpeg9_version_mismatch'))) {
        $destRoot = Split-Path (Split-Path $FfmpegPath -Parent) -Parent
        if ([string]::IsNullOrWhiteSpace($destRoot)) { $destRoot = 'C:\FFmpeg9' }
        Install-Ffmpeg9FromGyan -DestRoot $destRoot -LogFile $LogFile -Force:(-not (Test-Path $FfmpegPath))
        Test-Ffmpeg9BinaryQuick -FfmpegExe $FfmpegPath -LogFile $LogFile
        $encoderCaps = Get-FfmpegEncoderCapabilities -FfmpegPath $FfmpegPath
        if ($ProfileMode -eq 'auto') {
            $plan = Select-JellyfinHardwareAcceleration -Hardware $hardware -EncoderCaps $encoderCaps
        }
        $result.actions += 'install_ffmpeg9'
        $result.changed = $true
        $patchConfigured = Test-JellyfinFfmpeg9PatchConfigured -FfmpegPath $FfmpegPath -ProgramRoot $ProgramRoot
    }

    $status = Get-JellyfinFfmpeg9Status -FfmpegPath $FfmpegPath -ProgramRoot $ProgramRoot
    $layout = Get-JellyfinLayout
    if (-not $layout) {
        throw 'Could not locate Jellyfin installation (encoding.xml). Install Jellyfin first.'
    }

    $needsConfig = if ($ProfileMode -eq 'manual') {
        @('encoder_path_mismatch', 'encoding_xml_missing') | Where-Object { $status.issues -contains $_ }
    }
    else {
        @(
            'encoder_path_mismatch',
            'hw_accel_mismatch',
            'vpp_tonemap_mismatch',
            'encoding_xml_missing'
        ) | Where-Object { $status.issues -contains $_ }
    }

    $needsRestore = ($status.issues -contains 'binary_swap_detected')

    if ($status.status -eq 'ok' -and -not $needsRestore) {
        Write-LogLine -Message ("Action preserve [{0}/{1}]: FFmpeg 9 patch active; config unchanged" -f $RepairAction, $ProfileMode) -LogFile $LogFile
        $result.actions += 'preserve_config'

        if (-not $savedConfig.applied_at) {
            Save-ProgramUserConfig -ProgramRoot $ProgramRoot -ProfileMode $ProfileMode -HardwareSnapshot (New-HardwareSnapshot -Hardware $hardware -Plan $plan -ProfileMode $ProfileMode)
            $result.actions += 'migrate_user_config'
        }

        $result.after = $status
        return $result
    }

    $fullApply = ($needsConfig -contains 'encoding_xml_missing') -or (
        ($RepairAction -eq 'Install') -and (-not $patchConfigured))

    if ($needsConfig -or $needsRestore) {
        Stop-JellyfinRuntime -LogFile $LogFile
        $result.actions += 'stop_jellyfin'

        if ($needsRestore) {
            $restored = Restore-JellyfinBundledFfmpeg -ServerDir $layout.ServerDir
            if ($restored.Count -gt 0) {
                $result.actions += ('restore_bundled:' + ($restored -join ','))
                $result.changed = $true
            }
        }

        if ($needsConfig) {
            $repairPlan = Get-JellyfinEncodingRepairProfile -Issues $needsConfig -ProfileMode $ProfileMode -FfmpegOverridePath $FfmpegPath -Hardware $hardware -EncoderCaps $encoderCaps -FullApply:$fullApply
            if ($repairPlan.ApplyMode -eq 'none' -or $repairPlan.Profile.Count -eq 0) {
                Write-LogLine -Message 'No encoding.xml keys require changes; preserving existing settings.' -LogFile $LogFile
                $result.actions += 'preserve_config'
            }
            else {
                $encodingXml = Join-Path $layout.ConfigDir 'encoding.xml'
                Apply-JellyfinEncodingProfile -EncodingXmlPath $encodingXml -Profile $repairPlan.Profile | Out-Null
                $result.actions += switch ($repairPlan.ApplyMode) {
                    'full' { if ($ProfileMode -eq 'manual') { 'apply_ffmpeg_path_only' } else { 'apply_auto_profile' } }
                    default { 'apply_surgical_repair' }
                }
                $result.changed = $true
            }

            Save-ProgramUserConfig -ProgramRoot $ProgramRoot -ProfileMode $ProfileMode -HardwareSnapshot (New-HardwareSnapshot -Hardware $hardware -Plan $plan -ProfileMode $ProfileMode)
            $result.actions += 'save_user_config'
        }

        Start-JellyfinRuntime -LogFile $LogFile
        $result.actions += 'start_jellyfin'
    }

    $result.after = Get-JellyfinFfmpeg9Status -FfmpegPath $FfmpegPath -ProgramRoot $ProgramRoot
    Write-LogLine -Message ("Action done [{0}/{1}]: {2}" -f $RepairAction, $ProfileMode, $result.after.message) -LogFile $LogFile

    if (-not $Quiet -and $ProfileMode -eq 'auto' -and $plan -and ($result.actions -notcontains 'preserve_config')) {
        Show-HardwareTuningSummary -Hardware $hardware -Plan $plan -ProfileMode $ProfileMode
    }

    return $result
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$runtimeRoot = if (Test-Path (Join-Path $ProgramRoot 'lib\JellyfinMediaCommon.ps1')) { $ProgramRoot } else { $ScriptRoot }
$commonLib = Join-Path $runtimeRoot 'lib\JellyfinMediaCommon.ps1'
$installLib = Join-Path $runtimeRoot 'lib\Install-Ffmpeg9.ps1'
$tuningLib = Join-Path $runtimeRoot 'lib\Hardware-Tuning.ps1'
if (-not (Test-Path $commonLib)) { throw "Missing library: $commonLib" }
if (-not (Test-Path $installLib)) { throw "Missing library: $installLib" }
if (-not (Test-Path $tuningLib)) { throw "Missing library: $tuningLib" }
. $commonLib
. $installLib
. $tuningLib

if ($Action -ne 'Test' -and -not $Elevated -and -not (Test-IsAdministrator)) {
    Invoke-ElevatedSelf
    exit 0
}

$ffmpegPath = Join-Path $FfmpegRoot 'bin\ffmpeg.exe'
$savedConfig = Get-ProgramUserConfig -ProgramRoot $ProgramRoot
$shouldPrompt = $Interactive -and $Action -eq 'Install' -and -not $Json -and -not $savedConfig.profile_mode -and -not (Test-JellyfinFfmpeg9PatchConfigured -FfmpegPath $ffmpegPath -ProgramRoot $ProgramRoot)
$profileMode = Resolve-JellyfinProfileModeForAction -Action $Action -AutoTune:$AutoTune -ManualConfig:$ManualConfig -Interactive:$shouldPrompt -Quiet:($Json -or -not $shouldPrompt) -FfmpegPath $ffmpegPath -ProgramRoot $ProgramRoot -SavedConfig $savedConfig

try {
    switch ($Action) {
        'Deploy' {
            Invoke-DeployProgram -SourceRoot $ScriptRoot -TargetRoot $ProgramRoot
            if ($Json) {
                @{ status = 'ok'; message = "Deployed to $ProgramRoot" } | ConvertTo-Json -Compress
            }
            else {
                Write-Output "Deployed to $ProgramRoot"
            }
            exit 0
        }
        'Test' {
            $status = Get-JellyfinFfmpeg9Status -FfmpegPath $ffmpegPath -ProgramRoot $ProgramRoot
            if ($Json) {
                ($status | ConvertTo-Json -Compress -Depth 4)
            }
            else {
                Write-Output $status.message
            }
            if ($status.status -eq 'alert') { exit 1 }
            exit 0
        }
        'Repair' {
            $result = Invoke-RepairJellyfinFfmpeg9 -FfmpegPath $ffmpegPath -LogFile $LogFile -ProgramRoot $ProgramRoot -ProfileMode $profileMode -RepairAction 'Repair' -AllowDownload:(-not $SkipFfmpegDownload) -Quiet:([bool]$Json)
            if ($Json) {
                $result | ConvertTo-Json -Depth 5 -Compress
            }
            else {
                Write-Output $result.after.message
            }
            if ($result.after.status -eq 'alert') { exit 1 }
            exit 0
        }
        default {
            Write-LogLine -Message '=== Jellyfin FFmpeg 9 program: Install ===' -LogFile $LogFile

            if (-not $SkipDeploy) {
                Write-LogLine -Message 'Deploying program files...' -LogFile $LogFile
                Invoke-DeployProgram -SourceRoot $ScriptRoot -TargetRoot $ProgramRoot
                $commonLib = Join-Path $ProgramRoot 'lib\JellyfinMediaCommon.ps1'
                $installLib = Join-Path $ProgramRoot 'lib\Install-Ffmpeg9.ps1'
                $tuningLib = Join-Path $ProgramRoot 'lib\Hardware-Tuning.ps1'
                . $commonLib
                . $installLib
                . $tuningLib
            }

            if (-not $SkipFfmpegDownload) {
                Install-Ffmpeg9FromGyan -DestRoot $FfmpegRoot -LogFile $LogFile
                Test-Ffmpeg9BinaryQuick -FfmpegExe $ffmpegPath -LogFile $LogFile
            }

            $result = Invoke-RepairJellyfinFfmpeg9 -FfmpegPath $ffmpegPath -LogFile $LogFile -ProgramRoot $ProgramRoot -ProfileMode $profileMode -RepairAction 'Install' -AllowDownload:$false -Quiet:$false
            $layout = Get-JellyfinLayout

            Write-Host ''
            Write-Host '=== Jellyfin FFmpeg 9 install complete ===' -ForegroundColor Green
            Write-Host "Mode:    $profileMode ($(if ($profileMode -eq 'manual') { 'FFmpeg path only' } else { 'hardware auto-tune' }))"
            Write-Host "FFmpeg:  $ffmpegPath"
            Write-Host "Config:  $(Join-Path $layout.ConfigDir 'encoding.xml')"
            Write-Host "Program: $ProgramRoot"
            Write-Host "Logs:    $LogFile"
            if ($result.actions -contains 'preserve_config') {
                Write-Host 'FFmpeg 9 patch already active; existing Jellyfin settings were preserved.'
            }
            Write-Host ''
            Write-Host 'Verify: force a transcode; Dashboard -> Active Devices should show Transcode (hw).'
            Write-Host 'After a Jellyfin update, run Repair to restore only drifted FFmpeg 9 settings:'
            Write-Host "  & '$ProgramRoot\Install-JellyfinFfmpeg9.ps1' -Action Repair"
            Write-Host ''

            if ($Json) {
                @{
                    status = $result.after.status
                    message = $result.after.message
                    ffmpeg_path = $ffmpegPath
                    program_root = $ProgramRoot
                } | ConvertTo-Json -Compress
            }

            if ($result.after.status -eq 'alert') { exit 1 }
        }
    }
}
catch {
    $errorLine = "ERROR: $($_.Exception.Message)"
    try {
        Write-LogLine -Message $errorLine -LogFile $LogFile
    }
    catch {
        Add-Content -Path $LogFile -Value ((Get-Date -Format o) + ' ' + $errorLine) -Encoding UTF8
    }
    if ($Json) {
        @{ status = 'alert'; message = $_.Exception.Message } | ConvertTo-Json -Compress
    }
    throw
}
