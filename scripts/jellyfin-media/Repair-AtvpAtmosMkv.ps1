#Requires -Version 5.1
<#
.SYNOPSIS
  Remux ATVP/TBK multi-language Dolby Atmos WEB-DL MKVs for Jellyfin-friendly playback.

.DESCRIPTION
  Some Apple TV+ WEB-DL releases ship Italian audio first, no default English track,
  forced Italian subtitles, and 40+ foreign subtitle streams. Jellyfin spends a long
  time extracting every subtitle on play and clients may pick the wrong audio.

  This script stream-copies video/audio/subtitles into a cleaner layout:
    - English Atmos (E-AC-3) first and marked default
    - Italian Atmos second (when present)
    - English subtitles only (SDH track default when available)
    - Chapters preserved

.PARAMETER Path
  One or more MKV files, or directories to scan recursively.

.PARAMETER DryRun
  Report files that need repair without remuxing or replacing originals.

.PARAMETER KeepOriginal
  Write *.repaired.mkv beside the source instead of swapping in place.

.EXAMPLE
  .\Repair-AtvpAtmosMkv.ps1 "E:\Video\TV SHOWS\Silo\Season 3\Silo.S03E09*.mkv"

.EXAMPLE
  .\Repair-AtvpAtmosMkv.ps1 -Path "E:\Video\TV SHOWS\Silo\Season 3" -Recurse
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, ValueFromPipeline = $true, Position = 0)]
    [string[]]$Path,

    [switch]$Recurse,
    [switch]$DryRun,
    [switch]$KeepOriginal,

    [string]$FfmpegPath = 'C:\FFmpeg9\bin\ffmpeg.exe',
    [string]$FfprobePath = 'C:\FFmpeg9\bin\ffprobe.exe',
    [string]$LogFile = 'C:\ProgramData\Jellyfin\logs\atvp-atmos-repair.log'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\JellyfinMediaCommon.ps1')

function Write-RepairLog {
    param([string]$Message)
    Write-LogLine -Message $Message -LogFile $LogFile
}

function Get-MkvCandidates {
    param([string[]]$Roots, [switch]$Recurse)

    $files = @()
    foreach ($root in $Roots) {
        if (-not (Test-Path $root)) {
            Write-Warning "Path not found: $root"
            continue
        }
        if ((Get-Item $root).PSIsContainer) {
            $params = @{
                Path = $root
                Filter = '*.mkv'
                File = $true
                ErrorAction = 'SilentlyContinue'
            }
            if ($Recurse) { $params.Recurse = $true }
            $files += Get-ChildItem @params
        }
        else {
            $files += Get-Item $root
        }
    }

    return $files |
        Where-Object {
            $_.Extension -ieq '.mkv' -and
            $_.Name -notmatch '\.(repaired|orig)\.mkv$'
        } |
        Sort-Object FullName -Unique
}

function Invoke-ToolOutput {
    param(
        [string]$Exe,
        [string[]]$ArgumentList,
        [int]$TimeoutSeconds = 120
    )

    if (-not (Test-Path $Exe)) {
        throw "Missing executable: $Exe"
    }

    $stdoutFile = [IO.Path]::GetTempFileName()
    $stderrFile = [IO.Path]::GetTempFileName()
    try {
        $job = Start-Job -ScriptBlock {
            param($Tool, $ToolArgs, $OutFile, $ErrFile)
            & $Tool @ToolArgs 1> $OutFile 2> $ErrFile
            return $LASTEXITCODE
        } -ArgumentList $Exe, $ArgumentList, $stdoutFile, $stderrFile

        $completed = Wait-Job -Job $job -Timeout $TimeoutSeconds
        if (-not $completed) {
            Stop-Job -Job $job -Force
            Remove-Job -Job $job -Force
            throw "Timed out after ${TimeoutSeconds}s: $Exe"
        }

        $exitCode = Receive-Job -Job $job
        Remove-Job -Job $job -Force

        return [pscustomobject]@{
            ExitCode = [int]$exitCode
            StdOut = (Get-Content -LiteralPath $stdoutFile -Raw -ErrorAction SilentlyContinue)
            StdErr = (Get-Content -LiteralPath $stderrFile -Raw -ErrorAction SilentlyContinue)
        }
    }
    finally {
        Remove-Item -LiteralPath $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue
    }
}

function Get-StreamLayout {
    param([string]$InputPath)

    $probeArgs = @(
        '-hide_banner', '-loglevel', 'error',
        '-show_streams', '-show_chapters',
        '-of', 'json',
        $InputPath
    )
    $result = Invoke-ToolOutput -Exe $FfprobePath -ArgumentList $probeArgs -TimeoutSeconds 120
    if ($result.ExitCode -ne 0) {
        throw "ffprobe failed for ${InputPath}: $($result.StdErr)"
    }

    return ($result.StdOut | ConvertFrom-Json)
}

function Get-RepairMaps {
    param($Layout)

    $video = @($Layout.streams | Where-Object { $_.codec_type -eq 'video' } | Select-Object -First 1)
    if (-not $video) { throw 'No video stream found.' }

    $audio = @($Layout.streams | Where-Object { $_.codec_type -eq 'audio' })
    $engAudio = @($audio | Where-Object { $_.tags.language -eq 'eng' })
    $itaAudio = @($audio | Where-Object { $_.tags.language -eq 'ita' })
    $engSubs = @($Layout.streams | Where-Object { $_.codec_type -eq 'subtitle' -and $_.tags.language -eq 'eng' })

    if ($engAudio.Count -lt 1) {
        throw 'No English audio stream found.'
    }

    $maps = @("-map", "0:$($video.index)")
    foreach ($stream in $engAudio) { $maps += @('-map', "0:$($stream.index)") }
    foreach ($stream in $itaAudio) { $maps += @('-map', "0:$($stream.index)") }
    foreach ($stream in $engSubs) { $maps += @('-map', "0:$($stream.index)") }

    return [pscustomobject]@{
        Maps = $maps
        EngAudioCount = $engAudio.Count
        ItaAudioCount = $itaAudio.Count
        EngSubCount = $engSubs.Count
    }
}

function Test-NeedsAtvpAtmosRepair {
    param($Layout)

    $audio = @($Layout.streams | Where-Object { $_.codec_type -eq 'audio' })
    $subs = @($Layout.streams | Where-Object { $_.codec_type -eq 'subtitle' })
    if ($audio.Count -lt 1) { return $false }

    $firstAudio = $audio | Select-Object -First 1
    $engAudio = @($audio | Where-Object { $_.tags.language -eq 'eng' })
    $engDefault = @($engAudio | Where-Object { $_.disposition.default -eq 1 })

    $badAudioOrder = ($firstAudio.tags.language -ne 'eng')
    $missingEngDefault = ($engAudio.Count -gt 0 -and $engDefault.Count -eq 0)
    $subtitleBloat = ($subs.Count -gt 8)

    $forcedDefaultSub = $subs | Where-Object {
        $_.disposition.default -eq 1 -and $_.tags.language -ne 'eng'
    } | Select-Object -First 1

    return [pscustomobject]@{
        NeedsRepair = ($badAudioOrder -or $missingEngDefault -or $subtitleBloat -or [bool]$forcedDefaultSub)
        BadAudioOrder = $badAudioOrder
        MissingEngDefault = $missingEngDefault
        SubtitleBloat = $subtitleBloat
        ForcedForeignDefaultSub = [bool]$forcedDefaultSub
        AudioCount = $audio.Count
        SubtitleCount = $subs.Count
        FirstAudioLanguage = $firstAudio.tags.language
    }
}

function Repair-AtvpAtmosMkvFile {
    param(
        [System.IO.FileInfo]$File,
        [switch]$DryRun,
        [switch]$KeepOriginal
    )

    $layout = Get-StreamLayout -InputPath $File.FullName
    $analysis = Test-NeedsAtvpAtmosRepair -Layout $layout
    if (-not $analysis.NeedsRepair) {
        Write-RepairLog "SKIP (already OK): $($File.Name)"
        return [pscustomobject]@{ File = $File.FullName; Status = 'skipped'; Analysis = $analysis }
    }

    $reason = (@(
        $(if ($analysis.BadAudioOrder) { "audio-first=$($analysis.FirstAudioLanguage)" }),
        $(if ($analysis.MissingEngDefault) { 'no-default-eng-audio' }),
        $(if ($analysis.SubtitleBloat) { "subs=$($analysis.SubtitleCount)" }),
        $(if ($analysis.ForcedForeignDefaultSub) { 'forced-foreign-default-sub' })
    ) | Where-Object { $_ }) -join ', '

    Write-RepairLog "REPAIR: $($File.Name) [$reason]"

    if ($DryRun) {
        return [pscustomobject]@{ File = $File.FullName; Status = 'dryrun'; Analysis = $analysis; Reason = $reason }
    }

    $tempOut = [IO.Path]::ChangeExtension($File.FullName, '.repairing.mkv')
    if (Test-Path $tempOut) { Remove-Item $tempOut -Force }

    $mapInfo = Get-RepairMaps -Layout $layout
    $ffmpegArgs = @(
        '-hide_banner', '-loglevel', 'error', '-y',
        '-i', $File.FullName
    ) + $mapInfo.Maps + @(
        '-map_chapters', '0',
        '-c', 'copy',
        '-disposition:a:0', 'default'
    )

    if ($mapInfo.EngSubCount -gt 0) {
        $defaultSubIndex = $mapInfo.EngSubCount - 1
        $ffmpegArgs += @("-disposition:s:$defaultSubIndex", 'default')
    }

    $ffmpegArgs += $tempOut

    $result = Invoke-ToolOutput -Exe $FfmpegPath -ArgumentList $ffmpegArgs -TimeoutSeconds 7200
    if ($result.ExitCode -ne 0) {
        if (Test-Path $tempOut) { Remove-Item $tempOut -Force -ErrorAction SilentlyContinue }
        throw "ffmpeg remux failed for $($File.Name): $($result.StdErr)"
    }

    $finalOut = if ($KeepOriginal) {
        [IO.Path]::ChangeExtension($File.FullName, '.repaired.mkv')
    }
    else {
        $File.FullName
    }

    if (-not $KeepOriginal) {
        $backup = [IO.Path]::ChangeExtension($File.FullName, '.orig.mkv')
        if (-not (Test-Path $backup)) {
            Move-Item -LiteralPath $File.FullName -Destination $backup -Force
            Write-RepairLog "Backup: $backup"
        }
        else {
            Remove-Item -LiteralPath $File.FullName -Force
            Write-RepairLog "Backup already exists; removed damaged original"
        }
    }

    Move-Item -LiteralPath $tempOut -Destination $finalOut -Force
    Write-RepairLog "Done: $finalOut"

    return [pscustomobject]@{
        File = $File.FullName
        Output = $finalOut
        Status = 'repaired'
        Analysis = $analysis
        Reason = $reason
    }
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile -Parent) | Out-Null
Write-RepairLog '=== ATVP Atmos MKV repair start ==='

$candidates = Get-MkvCandidates -Roots $Path -Recurse:$Recurse
if (-not $candidates) {
    Write-RepairLog 'No MKV candidates found.'
    exit 0
}

$results = @()
foreach ($file in $candidates) {
    try {
        $results += Repair-AtvpAtmosMkvFile -File $file -DryRun:$DryRun -KeepOriginal:$KeepOriginal
    }
    catch {
        Write-RepairLog "ERROR $($file.Name): $($_.Exception.Message)"
        $results += [pscustomobject]@{ File = $file.FullName; Status = 'error'; Error = $_.Exception.Message }
    }
}

$repaired = @($results | Where-Object { $_.Status -eq 'repaired' }).Count
$skipped = @($results | Where-Object { $_.Status -eq 'skipped' }).Count
$planned = @($results | Where-Object { $_.Status -eq 'dryrun' }).Count
$errors = @($results | Where-Object { $_.Status -eq 'error' }).Count

Write-RepairLog "=== Done: repaired=$repaired skipped=$skipped dryrun=$planned errors=$errors ==="
$results | Format-Table File, Status, Reason, Error -AutoSize
if ($errors -gt 0) { exit 1 }
exit 0
