Set-StrictMode -Version Latest

function Get-SevenZipPath {
    @(
        'C:\Program Files\7-Zip\7z.exe',
        'C:\Program Files (x86)\7-Zip\7z.exe'
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

function Install-Ffmpeg9FromGyan {
    param(
        [string]$DestRoot,
        [string]$LogFile,
        [switch]$Force
    )

    $binExe = Join-Path $DestRoot 'bin\ffmpeg.exe'
    if (-not $Force -and (Test-Path $binExe)) {
        $version = Get-FfmpegVersionQuick -FfmpegPath $binExe
        if ($version -and ($version -match '^9(\.|$|-)')) {
            Write-LogLine -Message "FFmpeg 9 already present at $binExe ($version)" -LogFile $LogFile
            return $binExe
        }
    }

    $sevenZip = Get-SevenZipPath
    if (-not $sevenZip) {
        throw '7-Zip is required to extract gyan.dev FFmpeg builds. Install from https://www.7zip.org/'
    }

    $url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z'
    $temp7z = Join-Path $env:TEMP 'ffmpeg-release-full.7z'
    $extractRoot = Join-Path $env:TEMP ('ffmpeg-gyan-extract-' + (Get-Date -Format 'yyyyMMddHHmmss'))

    Write-LogLine -Message 'Downloading FFmpeg 9.0 full build from gyan.dev...' -LogFile $LogFile
    Invoke-WebRequest -Uri $url -OutFile $temp7z -UseBasicParsing

    New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null
    Write-LogLine -Message "Extracting $temp7z" -LogFile $LogFile
    & $sevenZip x $temp7z "-o$extractRoot" -y | Out-Null

    $binDir = Get-ChildItem -Path $extractRoot -Recurse -Directory -Filter 'bin' |
        Where-Object { Test-Path (Join-Path $_.FullName 'ffmpeg.exe') } |
        Select-Object -First 1
    if (-not $binDir) {
        throw 'Could not find ffmpeg.exe in extracted gyan.dev archive.'
    }

    if (Test-Path $DestRoot) {
        Remove-Item -Path $DestRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $DestRoot 'bin') | Out-Null
    Get-ChildItem -Path $binDir.FullName -File | ForEach-Object {
        $destFile = Join-Path (Join-Path $DestRoot 'bin') $_.Name
        Copy-Item -Path $_.FullName -Destination $destFile -Force
    }

    Write-LogLine -Message "Installed gyan.dev FFmpeg 9.0 to $(Join-Path $DestRoot 'bin')" -LogFile $LogFile
    return (Join-Path $DestRoot 'bin\ffmpeg.exe')
}

function Test-Ffmpeg9BinaryQuick {
    param(
        [string]$FfmpegExe,
        [string]$LogFile
    )

    if (-not (Test-Path $FfmpegExe)) {
        throw "ffmpeg not found: $FfmpegExe"
    }

    $versionLine = & $FfmpegExe -hide_banner -version 2>&1 | Select-Object -First 1
    Write-LogLine -Message "Binary probe: $versionLine" -LogFile $LogFile

    if ($versionLine -notmatch 'ffmpeg version 9(\.|\\s|$|-)') {
        throw "Expected FFmpeg 9.x, got: $versionLine"
    }

    $encoders = & $FfmpegExe -hide_banner -encoders 2>&1
    if ($encoders | Select-String -Pattern 'h264_qsv|hevc_qsv|av1_qsv') {
        Write-LogLine -Message 'QSV encoders detected in binary.' -LogFile $LogFile
    }
    else {
        Write-LogLine -Message 'WARNING: No QSV encoders reported in ffmpeg -encoders output.' -LogFile $LogFile
    }
}
