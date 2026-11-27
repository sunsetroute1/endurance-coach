#Requires -Version 5.1
<#
.SYNOPSIS
  Keep Jellyfin from transcoding just to burn image subtitles.

.DESCRIPTION
  Jellyfin Web cannot render PGS/VobSub without a full video transcode.
  This script:
    1. Tells Bazarr to fetch English SRT sidecars (does not extract from video)
    2. Optionally unsets default/forced on image subtitle tracks (mkvpropedit)
    3. Embedded-track extraction is opt-in only and off by default

.PARAMETER Path
  MKV file(s) or library roots. Defaults to Movies and TV SHOWS.

.PARAMETER SkipPath
  Full paths to skip (e.g. the file currently playing in Jellyfin).

.PARAMETER SkipJellyfin
  Do not refresh Jellyfin metadata (passed through to Python).

.PARAMETER SurveyOnly
  Count sidecar / extractable / image-only MKVs and exit without changes.

.PARAMETER SkipBazarr
  Only process MKVs; do not talk to Bazarr.

.EXAMPLE
  .\Ensure-TextSubtitles.ps1 -SkipJellyfin
#>
[CmdletBinding()]
param(
    [string[]]$Path = @('E:\Video\MOVIES', 'E:\Video\TV SHOWS'),
    [string[]]$SkipPath = @(
        'E:\Video\MOVIES\Action, sci-fi, etc\Black.Sheep.1996.BRRIP.X264.AAC.CrEwSaDe\Black.Sheep.1996.BRRIP.X264.AAC.CrEwSaDe.mkv'
    ),
    [string[]]$Title = @(),
    [switch]$Recurse,
    [switch]$SkipBazarr,
    [switch]$SkipJellyfin,
    [switch]$SurveyOnly,
    [switch]$ExtractEmbedded,
    [switch]$ClearDefaults,
    [string]$FfprobePath = 'C:\FFmpeg9\bin\ffprobe.exe',
    [string]$FfmpegPath = 'C:\FFmpeg9\bin\ffmpeg.exe',
    [string]$MkvPropEditPath = 'C:\Program Files\MKVToolNix\mkvpropedit.exe',
    [string]$PythonScript = '',
    [string]$LogFile = 'C:\ProgramData\Jellyfin\logs\text-subtitles.log'
)

if (-not $PythonScript) {
    $PythonScript = Join-Path $PSScriptRoot 'ensure_text_subtitles.py'
}

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'lib\JellyfinMediaCommon.ps1')

$script:ImageCodecs = @('hdmv_pgs_subtitle', 'dvd_subtitle', 'dvb_subtitle', 'pgssub', 'hdmv_text_subtitle')
$script:TextCodecs = @('subrip', 'srt', 'ass', 'ssa', 'webvtt', 'mov_text')

function Write-SubLog {
    param([string]$Message)
    Write-LogLine -Message $Message -LogFile $LogFile
}

function Test-SkipPath {
    param([string]$FullName)
    foreach ($skip in $SkipPath) {
        if ($FullName -ieq $skip) { return $true }
    }
    return $false
}

function Get-MovieMkvs {
    param([string[]]$Roots, [switch]$Recurse)

    $files = @()
    foreach ($root in $Roots) {
        if (-not (Test-Path -LiteralPath $root)) {
            Write-Warning "Path not found: $root"
            continue
        }
        $item = Get-Item -LiteralPath $root
        if ($item.PSIsContainer) {
            $params = @{
                LiteralPath = $root
                Filter      = '*.mkv'
                File        = $true
                ErrorAction = 'SilentlyContinue'
            }
            if ($Recurse -or $Roots.Count -ge 1) {
                $params.Recurse = $true
            }
            $files += Get-ChildItem @params
        }
        else {
            $files += $item
        }
    }
    return @(
        $files |
            Where-Object { $_.Extension -ieq '.mkv' -and -not (Test-SkipPath -FullName $_.FullName) } |
            Sort-Object FullName -Unique
    )
}

function Get-EnglishSidecarPaths {
    param([System.IO.FileInfo]$File)

    $dir = $File.DirectoryName
    $base = [IO.Path]::GetFileNameWithoutExtension($File.Name)
    $candidates = @(
        (Join-Path $dir ($base + '.en.srt')),
        (Join-Path $dir ($base + '.eng.srt')),
        (Join-Path $dir ($base + '.en.vtt')),
        (Join-Path $dir ($base + '.eng.vtt')),
        (Join-Path $dir ($base + '.srt')),
        (Join-Path $dir ($base + '.vtt'))
    )
    foreach ($sidecar in @(Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue)) {
        $name = $sidecar.Name
        $isSidecar = $name -like '*.srt' -or $name -like '*.vtt'
        $belongsToFile = $name.StartsWith("$base.en.", [StringComparison]::OrdinalIgnoreCase) -or
            $name.StartsWith("$base.eng.", [StringComparison]::OrdinalIgnoreCase)
        if ($isSidecar -and $belongsToFile) {
            $candidates += $sidecar.FullName
        }
    }
    return @($candidates | Select-Object -Unique)
}

function Test-HasEnglishSidecar {
    param([System.IO.FileInfo]$File)

    foreach ($candidate in (Get-EnglishSidecarPaths -File $File)) {
        if ((Test-Path -LiteralPath $candidate) -and ((Get-Item -LiteralPath $candidate).Length -gt 0)) {
            return $true
        }
    }
    return $false
}

function Get-SubtitleStreams {
    param([string]$InputPath)

    if (-not (Test-Path -LiteralPath $FfprobePath)) {
        throw "ffprobe not found: $FfprobePath"
    }
    $json = & $FfprobePath -v error -show_streams `
        -show_entries 'stream=index,codec_type,codec_name:stream_tags=language:stream_disposition=default,forced' `
        -of json -- $InputPath 2>&1
    if ($LASTEXITCODE -ne 0 -or -not $json) {
        throw "ffprobe failed for $InputPath"
    }
    $probe = ($json | Out-String) | ConvertFrom-Json
    return @($probe.streams | Where-Object { $_.codec_type -eq 'subtitle' })
}

function Test-EnglishLanguage {
    param([object]$Stream)
    $lang = ''
    if ($Stream.PSObject.Properties['tags'] -and $Stream.tags) {
        if ($Stream.tags.PSObject.Properties['language']) {
            $lang = [string]$Stream.tags.language
        }
    }
    if (-not $lang) { return $false }
    $lang = $lang.ToLowerInvariant()
    return ($lang -in @('en', 'eng', 'english')) -or $lang.StartsWith('en-')
}

function Get-BestTextExtractTrack {
    param([object[]]$Streams)

    $text = @(
        $Streams | Where-Object { $script:TextCodecs -contains [string]$_.codec_name }
    )
    if ($text.Count -lt 1) { return $null }
    $english = @($text | Where-Object { Test-EnglishLanguage -Stream $_ })
    if ($english.Count -ge 1) { return $english[0] }
    return $text[0]
}

function Get-StreamDispositionFlag {
    param(
        [object]$Stream,
        [ValidateSet('default', 'forced')]
        [string]$Name
    )
    if (-not $Stream.PSObject.Properties['disposition'] -or -not $Stream.disposition) {
        return 0
    }
    if ($Stream.disposition.PSObject.Properties[$Name]) {
        return [int]$Stream.disposition.$Name
    }
    return 0
}

function Get-TracksNeedingDefaultClear {
    param([object[]]$Streams)

    return @(
        $Streams | Where-Object {
            $codec = [string]$_.codec_name
            $isImage = $script:ImageCodecs -contains $codec
            $isText = $script:TextCodecs -contains $codec
            ($isImage -or $isText) -and (
                (Get-StreamDispositionFlag -Stream $_ -Name 'default') -eq 1 -or
                (Get-StreamDispositionFlag -Stream $_ -Name 'forced') -eq 1
            )
        }
    )
}

function Test-FileReadable {
    param([string]$FullName)
    try {
        $fs = [System.IO.File]::Open($FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $fs.Close()
        return $true
    }
    catch {
        return $false
    }
}

function Export-TextSubSidecar {
    param(
        [System.IO.FileInfo]$File,
        [object]$Track
    )

    if (-not (Test-Path -LiteralPath $FfmpegPath)) {
        throw "ffmpeg not found: $FfmpegPath"
    }
    $base = [IO.Path]::GetFileNameWithoutExtension($File.Name)
    $sidecar = Join-Path $File.DirectoryName ($base + '.en.srt')
    if (Test-Path -LiteralPath $sidecar) {
        return [pscustomobject]@{ Sidecar = $sidecar; Status = 'exists' }
    }

    $mapIndex = [int]$Track.index
    $output = & $FfmpegPath -y -nostdin -loglevel error -i $File.FullName -map "0:$mapIndex" -c:s srt $sidecar 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $sidecar)) {
        throw "ffmpeg extract failed: $output"
    }
    if ((Get-Item -LiteralPath $sidecar).Length -lt 1) {
        Remove-Item -LiteralPath $sidecar -Force -ErrorAction SilentlyContinue
        throw 'ffmpeg produced empty sidecar'
    }
    Write-SubLog "Extracted $($File.Name) track $mapIndex -> $(Split-Path $sidecar -Leaf)"
    return [pscustomobject]@{ Sidecar = $sidecar; Status = 'extracted' }
}

function Clear-SubtitleDefaults {
    param(
        [System.IO.FileInfo]$File,
        [object[]]$Tracks
    )

    if ($Tracks.Count -lt 1) {
        return 0
    }
    if (-not (Test-Path -LiteralPath $MkvPropEditPath)) {
        throw "mkvpropedit not found: $MkvPropEditPath"
    }

    $args = @($File.FullName)
    foreach ($track in $Tracks) {
        $mkvTrack = [int]$track.index + 1
        $args += @(
            '--edit', "track:$mkvTrack",
            '--set', 'flag-default=0',
            '--set', 'flag-forced=0'
        )
    }
    $output = & $MkvPropEditPath @args 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "mkvpropedit failed for $($File.Name): $output"
    }
    Write-SubLog "Cleared default/forced subs on $($File.Name) ($($Tracks.Count) track(s))"
    return $Tracks.Count
}

function Get-MkvSurveyClass {
    param([System.IO.FileInfo]$File)

    if (-not (Test-FileReadable -FullName $File.FullName)) {
        return 'locked'
    }
    try {
        $streams = @(Get-SubtitleStreams -InputPath $File.FullName)
    }
    catch {
        return 'error'
    }
    if (Test-HasEnglishSidecar -File $File) {
        return 'sidecar-already'
    }
    if (Get-BestTextExtractTrack -Streams $streams) {
        return 'extractable-text'
    }
    $hasImage = @($streams | Where-Object { $script:ImageCodecs -contains [string]$_.codec_name }).Count -gt 0
    if ($hasImage) {
        return 'image-only'
    }
    if ($streams.Count -eq 0) {
        return 'no-subs'
    }
    return 'other'
}

New-Item -ItemType Directory -Force -Path (Split-Path $LogFile -Parent) | Out-Null
Write-SubLog '=== Ensure text subtitles start ==='

$skippedPlaying = @($SkipPath | Where-Object { $_ }).Count
$candidates = @()
if ($SurveyOnly -or $ExtractEmbedded -or $ClearDefaults) {
    $candidates = @(Get-MovieMkvs -Roots $Path -Recurse:$Recurse)
}

if ($SurveyOnly) {
    $survey = [ordered]@{
        scanned          = $candidates.Count
        sidecarAlready   = 0
        extractableText  = 0
        imageOnly        = 0
        noSubs           = 0
        other            = 0
        locked           = 0
        errors           = 0
    }

    foreach ($file in $candidates) {
        $class = Get-MkvSurveyClass -File $file
        switch ($class) {
            'sidecar-already' { $survey.sidecarAlready++ }
            'extractable-text' { $survey.extractableText++ }
            'image-only' { $survey.imageOnly++ }
            'no-subs' { $survey.noSubs++ }
            'locked' { $survey.locked++ }
            'error' { $survey.errors++ }
            default { $survey.other++ }
        }
    }

    Write-SubLog (
        "Survey: scanned=$($survey.scanned) sidecar-already=$($survey.sidecarAlready) " +
        "extractable-text=$($survey.extractableText) image-only=$($survey.imageOnly) " +
        "no-subs=$($survey.noSubs) locked=$($survey.locked) errors=$($survey.errors) skipped-path=$skippedPlaying"
    )
    Write-SubLog '=== Survey only; no changes ==='
    exit 0
}

if (-not $ExtractEmbedded -and -not $ClearDefaults) {
    Write-SubLog 'Skipping MKV extract/ffprobe pass; Bazarr will download SRT sidecars'
}

$extracted = 0
$defaultsCleared = 0
$ok = 0
$errors = 0

if ($ExtractEmbedded -or $ClearDefaults) {
    foreach ($file in $candidates) {
        if (-not (Test-FileReadable -FullName $file.FullName)) {
            Write-SubLog "SKIP locked: $($file.Name)"
            continue
        }
        try {
            $streams = @(Get-SubtitleStreams -InputPath $file.FullName)
            $changed = $false

            if ($ExtractEmbedded -and -not (Test-HasEnglishSidecar -File $file)) {
                $track = Get-BestTextExtractTrack -Streams $streams
                if ($track) {
                    $extractResult = Export-TextSubSidecar -File $file -Track $track
                    if ($extractResult.Status -eq 'extracted') {
                        $extracted++
                        $changed = $true
                    }
                }
            }

            if ($ClearDefaults) {
                $clearTracks = @(Get-TracksNeedingDefaultClear -Streams $streams)
                if ($clearTracks.Count -gt 0) {
                    $n = Clear-SubtitleDefaults -File $file -Tracks $clearTracks
                    $defaultsCleared += $n
                    $changed = $true
                }
            }

            if (-not $changed) { $ok++ }
        }
        catch {
            $errors++
            Write-SubLog "ERROR $($file.Name): $($_.Exception.Message)"
        }
    }

    Write-SubLog (
        "MKV pass: extracted=$extracted defaults-cleared-tracks=$defaultsCleared " +
        "already-ok=$ok errors=$errors scanned=$($candidates.Count)"
    )
}

if (-not $SkipBazarr) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command python.exe -ErrorAction SilentlyContinue }
    if (-not $python) {
        Write-SubLog 'WARNING: python not found; Bazarr fill-missing skipped'
    }
    else {
        $pyArgs = @($PythonScript, '--skip-restart')
        if ($SkipJellyfin) {
            $pyArgs += '--skip-jellyfin'
        }
        $pyArgs += '--fill-missing'
        foreach ($item in $Title) {
            $pyArgs += @('--title', $item)
        }
        Write-SubLog 'Running Bazarr fill-missing'
        & $python.Source @pyArgs
        if ($LASTEXITCODE -ne 0) {
            Write-SubLog "WARNING ensure_text_subtitles.py exited $LASTEXITCODE"
        }
    }
}

Write-SubLog '=== Ensure text subtitles done ==='
exit 0
