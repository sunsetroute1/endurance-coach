#Requires -Version 5.1
<#
.SYNOPSIS
  Creates a browser-friendly Jellyfin version of difficult HDR/high-frame-rate media.

.DESCRIPTION
  Uses Intel QSV to make a one-time H.264/AAC SDR MP4 that Jellyfin Web can direct
  play. The source is never changed. Image subtitles are intentionally omitted
  because browser clients cannot render PGS/VobSub and would force a video
  transcode to burn them in.

  This is intended for unusual sources such as 4K HEVC/Dolby Vision above 60 fps.
  It trades a one-time offline conversion for inexpensive playback on every stream.

.EXAMPLE
  .\New-JellyfinWebVersion.ps1 -Path 'E:\Video\MOVIES\Movie.2160p.DV.mkv'

.EXAMPLE
  .\New-JellyfinWebVersion.ps1 -Path 'E:\Video\MOVIES\Movie.2160p.DV.mkv' -AnalyzeOnly
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Path,

    [string]$OutputPath = '',
    [ValidateRange(480, 2160)]
    [int]$MaxWidth = 1920,
    [ValidateSet(24, 30, 50, 60)]
    [int]$MaxFrameRate = 60,
    [ValidateRange(1, 51)]
    [int]$Quality = 23,
    [switch]$AnalyzeOnly,
    [switch]$Force,

    [string]$FfmpegPath = 'C:\FFmpeg9\bin\ffmpeg.exe',
    [string]$FfprobePath = 'C:\FFmpeg9\bin\ffprobe.exe',
    [string]$LogFile = 'C:\ProgramData\Jellyfin\logs\web-version.log'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-WebVersionLog {
    param([string]$Message)
    $directory = Split-Path -Parent $LogFile
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -LiteralPath $LogFile -Value $line -Encoding utf8
    Write-Host $Message
}

function ConvertTo-Rate {
    param([string]$Text)
    if (-not $Text -or $Text -eq '0/0') { return 0.0 }
    if ($Text -match '^(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)$') {
        $denominator = [double]$Matches[2]
        if ($denominator -eq 0) { return 0.0 }
        return [double]$Matches[1] / $denominator
    }
    return [double]$Text
}

if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Media file not found: $Path"
}
foreach ($tool in @($FfmpegPath, $FfprobePath)) {
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) {
        throw "Required tool not found: $tool"
    }
}

$encoderList = & $FfmpegPath -hide_banner -encoders 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $encoderList -notmatch '\bh264_qsv\b') {
    throw 'FFmpeg does not expose h264_qsv; refusing a slow software conversion.'
}

$probeJson = & $FfprobePath -v error -show_streams -show_format -of json -- $Path
if ($LASTEXITCODE -ne 0 -or -not $probeJson) {
    throw "ffprobe could not inspect: $Path"
}
$probe = $probeJson | ConvertFrom-Json
$video = @($probe.streams | Where-Object { $_.codec_type -eq 'video' } | Select-Object -First 1)
$audio = @($probe.streams | Where-Object { $_.codec_type -eq 'audio' } | Select-Object -First 1)
$subtitles = @($probe.streams | Where-Object { $_.codec_type -eq 'subtitle' })
if (-not $video) { throw 'No video stream was found.' }
if (-not $audio) { throw 'No audio stream was found.' }

$sourceRate = ConvertTo-Rate ([string]$video.avg_frame_rate)
$targetRate = [Math]::Min([double]$MaxFrameRate, $sourceRate)
if ($targetRate -le 0) { $targetRate = [double]$MaxFrameRate }
$targetRateText = if ($targetRate -eq 60) { '60000/1001' } else { [string][int]$targetRate }

$sourceWidth = [int]$video.width
$sourceHeight = [int]$video.height
$targetWidth = [Math]::Min($MaxWidth, $sourceWidth)
$targetWidth -= $targetWidth % 2
$targetHeight = [int][Math]::Round(($sourceHeight * $targetWidth / $sourceWidth) / 2) * 2

$isHdr = (
    [string]$video.color_transfer -in @('smpte2084', 'arib-std-b67') -or
    ($video.PSObject.Properties['side_data_list'] -and
        (($video.side_data_list | ConvertTo-Json -Compress) -match 'DOVI|Dolby Vision'))
)
$imageSubtitleCount = @(
    $subtitles | Where-Object {
        [string]$_.codec_name -in @('hdmv_pgs_subtitle', 'dvd_subtitle', 'dvb_subtitle')
    }
).Count

if (-not $OutputPath) {
    $source = Get-Item -LiteralPath $Path
    $label = "Web ${targetWidth}x${targetHeight}p$([int]$targetRate)"
    $OutputPath = Join-Path $source.DirectoryName "$($source.BaseName) - $label.mp4"
}
$temporaryPath = [IO.Path]::ChangeExtension($OutputPath, '.creating.mp4')

$analysis = [ordered]@{
    source = (Resolve-Path -LiteralPath $Path).Path
    output = $OutputPath
    source_video = [ordered]@{
        codec = [string]$video.codec_name
        width = $sourceWidth
        height = $sourceHeight
        frame_rate = [Math]::Round($sourceRate, 3)
        pixel_format = [string]$video.pix_fmt
        color_transfer = [string]$video.color_transfer
        hdr = [bool]$isHdr
    }
    output_video = [ordered]@{
        codec = 'h264'
        width = $targetWidth
        height = $targetHeight
        frame_rate = $targetRateText
        pixel_format = 'yuv420p'
        color = 'bt709 SDR'
    }
    output_audio = 'AAC stereo'
    subtitles_omitted = $subtitles.Count
    image_subtitles_avoiding_burn_in = $imageSubtitleCount
}

Write-WebVersionLog (
    "Analyze: $Path => H.264 ${targetWidth}x${targetHeight}@$targetRateText, " +
    "HDR=$isHdr, omitted subtitles=$($subtitles.Count) (image=$imageSubtitleCount)"
)
if ($AnalyzeOnly) {
    $analysis | ConvertTo-Json -Depth 5
    exit 0
}

if ((Test-Path -LiteralPath $OutputPath) -and -not $Force) {
    throw "Output already exists (use -Force to replace it): $OutputPath"
}
Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue

$vpp = @(
    "w=$targetWidth",
    "h=$targetHeight",
    'format=nv12',
    "framerate=$targetRateText",
    "tonemap=$(if ($isHdr) { 1 } else { 0 })",
    'out_color_matrix=bt709',
    'out_color_primaries=bt709',
    'out_color_transfer=bt709'
) -join ':'

$arguments = @(
    '-hide_banner', '-y',
    '-analyzeduration', '200M',
    '-probesize', '1G',
    '-init_hw_device', 'qsv=hw',
    '-filter_hw_device', 'hw',
    '-hwaccel', 'qsv',
    '-hwaccel_output_format', 'qsv',
    '-i', $Path,
    '-map', '0:v:0',
    '-map', '0:a:0',
    '-map_metadata', '0',
    '-map_chapters', '0',
    '-vf', "vpp_qsv=$vpp",
    '-c:v', 'h264_qsv',
    '-preset', 'veryfast',
    '-global_quality', [string]$Quality,
    '-look_ahead', '0',
    '-c:a', 'aac',
    '-b:a', '256k',
    '-ac', '2',
    '-movflags', '+faststart',
    $temporaryPath
)

Write-WebVersionLog "Create start: $OutputPath"
try {
    & $FfmpegPath @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "FFmpeg exited with code $LASTEXITCODE"
    }

    $verifyJson = & $FfprobePath -v error `
        -show_entries 'format=duration,size:stream=codec_name,width,height,avg_frame_rate,pix_fmt,color_transfer' `
        -of json -- $temporaryPath
    if ($LASTEXITCODE -ne 0 -or -not $verifyJson) {
        throw 'The completed output could not be verified.'
    }
    $verified = $verifyJson | ConvertFrom-Json
    $verifiedVideo = @($verified.streams | Where-Object { $_.codec_name -eq 'h264' } | Select-Object -First 1)
    if (-not $verifiedVideo -or [int]$verifiedVideo.width -ne $targetWidth) {
        throw 'The completed output does not match the requested H.264 dimensions.'
    }

    if ((Test-Path -LiteralPath $OutputPath) -and $Force) {
        Remove-Item -LiteralPath $OutputPath -Force
    }
    Move-Item -LiteralPath $temporaryPath -Destination $OutputPath
    Write-WebVersionLog "Create complete: $OutputPath"
    [ordered]@{
        status = 'created'
        output = $OutputPath
        verification = $verified
        analysis = $analysis
    } | ConvertTo-Json -Depth 7
}
catch {
    Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
    Write-WebVersionLog "ERROR: $($_.Exception.Message)"
    throw
}
