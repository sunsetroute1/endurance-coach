# Shared helpers for Jellyfin + FFmpeg 9 media pipeline audit, validation, and configuration.
Set-StrictMode -Version Latest

function Write-LogLine {
    param(
        [string]$Message,
        [string]$LogFile
    )
    $line = '{0} {1}' -f (Get-Date -Format o), $Message
    if ($LogFile) {
        $dir = Split-Path -Parent $LogFile
        if ($dir -and -not (Test-Path $dir)) {
            New-Item -ItemType Directory -Force -Path $dir | Out-Null
        }
        Add-Content -Path $LogFile -Value $line -Encoding UTF8
    }
    Write-Host $Message
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-SafeCommandOutput {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 120
    )

    $result = [ordered]@{
        Path = $FilePath
        Arguments = ($Arguments -join ' ')
        ExitCode = $null
        StdOut = ''
        StdErr = ''
        Error = $null
    }

    if (-not (Test-Path $FilePath)) {
        $result.Error = "Missing executable: $FilePath"
        return [pscustomobject]$result
    }

    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $FilePath
        $psi.Arguments = ($Arguments -join ' ')
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
            try { $proc.Kill() } catch { }
            $result.Error = "Timed out after ${TimeoutSeconds}s"
        }
        $result.StdOut = $proc.StandardOutput.ReadToEnd()
        $result.StdErr = $proc.StandardError.ReadToEnd()
        $result.ExitCode = $proc.ExitCode
    }
    catch {
        $result.Error = $_.Exception.Message
    }

    return [pscustomobject]$result
}

function Get-JellyfinLayout {
    $candidates = @(
        [ordered]@{
            Style = 'Tray'
            ServerDir = 'C:\Program Files\Jellyfin\Server'
            ConfigDir = 'C:\ProgramData\Jellyfin\Server\config'
            DataDir = 'C:\ProgramData\Jellyfin\Server'
        },
        [ordered]@{
            Style = 'Portable'
            ServerDir = $null
            ConfigDir = Join-Path $env:LOCALAPPDATA 'jellyfin\config'
            DataDir = Join-Path $env:LOCALAPPDATA 'jellyfin'
        }
    )

    foreach ($item in $candidates) {
        $encoding = Join-Path $item.ConfigDir 'encoding.xml'
        $serverExe = if ($item.ServerDir) { Join-Path $item.ServerDir 'jellyfin.exe' } else { $null }
        $serverOk = (-not $item.ServerDir) -or (Test-Path $serverExe)
        if ((Test-Path $encoding) -and $serverOk) {
            if (-not $item.ServerDir) {
                $found = Get-ChildItem -Path $item.DataDir -Recurse -Filter 'jellyfin.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($found) {
                    $item.ServerDir = Split-Path -Parent $found.FullName
                }
            }
            return [pscustomobject]$item
        }
    }

    return $null
}

function Import-XmlFileSafe {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try {
        return [xml](Get-Content -Path $Path -Raw -Encoding UTF8)
    }
    catch {
        return $null
    }
}

function Backup-ConfigFile {
    param(
        [string]$Path,
        [string]$BackupRoot,
        [string]$Label = 'config'
    )

    if (-not (Test-Path $Path)) { return $null }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupDir = Join-Path $BackupRoot ($Label + '-' + $stamp)
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $dest = Join-Path $backupDir (Split-Path $Path -Leaf)
    Copy-Item -Path $Path -Destination $dest -Force
    return $dest
}

function Resolve-FfmpegExecutable {
    param(
        [ValidateSet('Active', 'Bundled', 'Override', 'Custom')]
        [string]$Profile = 'Active',
        [string]$CustomPath,
        [string]$DefaultOverridePath = 'C:\FFmpeg9\bin\ffmpeg.exe'
    )

    $layout = Get-JellyfinLayout
    switch ($Profile) {
        'Custom' {
            if (-not $CustomPath -or -not (Test-Path $CustomPath)) {
                throw "Custom FFmpeg path not found: $CustomPath"
            }
            return $CustomPath
        }
        'Override' {
            if (-not (Test-Path $DefaultOverridePath)) {
                throw "Override FFmpeg not found at $DefaultOverridePath"
            }
            return $DefaultOverridePath
        }
        'Bundled' {
            if (-not $layout -or -not $layout.ServerDir) {
                throw 'Jellyfin server directory not found for bundled FFmpeg lookup.'
            }
            $bak = Join-Path $layout.ServerDir 'ffmpeg.exe.bak'
            if (Test-Path $bak) { return $bak }
            $bundled = Join-Path $layout.ServerDir 'ffmpeg.exe'
            if (Test-Path $bundled) { return $bundled }
            throw 'Bundled FFmpeg not found.'
        }
        default {
            $encodingPath = if ($layout) { Join-Path $layout.ConfigDir 'encoding.xml' } else { $null }
            $encoding = if ($encodingPath) { Import-XmlFileSafe -Path $encodingPath } else { $null }
            if ($encoding -and $encoding.EncodingOptions.EncoderAppPath) {
                $configured = [string]$encoding.EncodingOptions.EncoderAppPath
                if ($configured -and (Test-Path $configured)) { return $configured }
            }
            if ($layout -and $layout.ServerDir) {
                $active = Join-Path $layout.ServerDir 'ffmpeg.exe'
                if (Test-Path $active) { return $active }
            }
            throw 'Could not resolve active FFmpeg executable.'
        }
    }
}

function Get-FfmpegExecutableForProbe {
    param([string]$FfmpegPath)

    if (-not (Test-Path $FfmpegPath)) { return $FfmpegPath }
    if ($FfmpegPath -notmatch '\.bak$') { return $FfmpegPath }

    $tempProbe = Join-Path $env:TEMP ('ffmpeg-probe-' + [IO.Path]::GetFileName($FfmpegPath))
    Copy-Item -Path $FfmpegPath -Destination $tempProbe -Force
    return $tempProbe
}

function Get-FfmpegProbe {
    param([string]$FfmpegPath)

    $probePath = Get-FfmpegExecutableForProbe -FfmpegPath $FfmpegPath

    $probe = [ordered]@{
        Path = $FfmpegPath
        Exists = $false
        VersionLine = $null
        ConfigureLine = $null
        FileVersion = $null
        BuildKind = 'Unknown'
        HasLibVpl = $false
        HasLibMfx = $false
        HasVulkan = $false
        HasOpenCl = $false
        HasLibplacebo = $false
        HasQsvEncoders = $false
        HasQsvDecoders = $false
        HasTonemapOpenCl = $false
        HasVppQsv = $false
        HasScaleQsv = $false
        Hwaccels = @()
        QsvEncoders = @()
        QsvDecoders = @()
        Error = $null
    }

    if (-not (Test-Path $FfmpegPath)) {
        return [pscustomobject]$probe
    }

    $probe.Exists = $true
    $probe.FileVersion = (Get-Item $FfmpegPath).VersionInfo.FileVersion

    $version = Get-SafeCommandOutput -FilePath $probePath -Arguments @('-version') -TimeoutSeconds 30
    if ($version.Error) {
        $probe.Error = $version.Error
        return [pscustomobject]$probe
    }

    $lines = ($version.StdOut + $version.StdErr) -split "`r?`n"
    $probe.VersionLine = ($lines | Where-Object { $_ -match '^ffmpeg version' } | Select-Object -First 1)
    $probe.ConfigureLine = ($lines | Where-Object { $_ -match '^configuration:' } | Select-Object -First 1)

    if ($probe.VersionLine -match 'Jellyfin') { $probe.BuildKind = 'Jellyfin-FFmpeg' }
    elseif ($probe.VersionLine -match 'gyan\.dev') { $probe.BuildKind = 'Gyan-Upstream' }
    elseif ($probe.VersionLine -match 'BtbN|btbn') { $probe.BuildKind = 'BtbN' }
    else { $probe.BuildKind = 'Upstream' }

    if ($probe.ConfigureLine) {
        $probe.HasLibVpl = $probe.ConfigureLine -match 'libvpl'
        $probe.HasLibMfx = $probe.ConfigureLine -match 'libmfx'
        $probe.HasVulkan = $probe.ConfigureLine -match 'vulkan'
        $probe.HasOpenCl = $probe.ConfigureLine -match 'opencl'
        $probe.HasLibplacebo = $probe.ConfigureLine -match 'libplacebo'
    }

    $hw = Get-SafeCommandOutput -FilePath $probePath -Arguments @('-hide_banner', '-hwaccels') -TimeoutSeconds 30
    if (-not $hw.Error) {
        $probe.Hwaccels = ($hw.StdOut + $hw.StdErr) -split "`r?`n" |
            Where-Object { $_ -and ($_ -notmatch '^Hardware acceleration methods:') } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    }

    $enc = Get-SafeCommandOutput -FilePath $probePath -Arguments @('-hide_banner', '-encoders') -TimeoutSeconds 60
    if (-not $enc.Error) {
        $probe.QsvEncoders = ($enc.StdOut + $enc.StdErr) -split "`r?`n" |
            Where-Object { $_ -match '_qsv\s' } |
            ForEach-Object { ($_ -split '\s+')[1].Trim() }
        $probe.HasQsvEncoders = $probe.QsvEncoders.Count -gt 0
    }

    $dec = Get-SafeCommandOutput -FilePath $probePath -Arguments @('-hide_banner', '-decoders') -TimeoutSeconds 60
    if (-not $dec.Error) {
        $probe.QsvDecoders = ($dec.StdOut + $dec.StdErr) -split "`r?`n" |
            Where-Object { $_ -match '_qsv\s' } |
            ForEach-Object { ($_ -split '\s+')[1].Trim() }
        $probe.HasQsvDecoders = $probe.QsvDecoders.Count -gt 0
    }

    $filters = Get-SafeCommandOutput -FilePath $probePath -Arguments @('-hide_banner', '-filters') -TimeoutSeconds 60
    if (-not $filters.Error) {
        $filterText = ($filters.StdOut + $filters.StdErr) -join "`n"
        $probe.HasTonemapOpenCl = $filterText -match 'tonemap_opencl'
        $probe.HasVppQsv = $filterText -match 'vpp_qsv'
        $probe.HasScaleQsv = $filterText -match 'scale_qsv'
    }

    return [pscustomobject]$probe
}

function Get-DiscoveredFfmpegInstalls {
    $paths = [System.Collections.Generic.List[string]]::new()
    $layout = Get-JellyfinLayout

    $candidates = @(
        'C:\FFmpeg9\bin\ffmpeg.exe',
        'C:\ffmpeg\bin\ffmpeg.exe',
        'C:\Program Files\ffmpeg\bin\ffmpeg.exe'
    )

    if ($layout -and $layout.ServerDir) {
        $candidates += (Join-Path $layout.ServerDir 'ffmpeg.exe')
        $bak = Join-Path $layout.ServerDir 'ffmpeg.exe.bak'
        if (Test-Path $bak) { $candidates += $bak }
    }

    $pathHits = Get-Command ffmpeg -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source }
    foreach ($item in ($candidates + $pathHits)) {
        if ($item -and (Test-Path $item) -and -not $paths.Contains($item)) {
            [void]$paths.Add($item)
        }
    }

    return $paths
}

function Get-JellyfinServerVersion {
    param([string]$ServerDir)

    if (-not $ServerDir) { return $null }
    $dll = Join-Path $ServerDir 'jellyfin.dll'
    if (-not (Test-Path $dll)) { return $null }

    try {
        return [System.Reflection.AssemblyName]::GetAssemblyName($dll).Version.ToString()
    }
    catch {
        return $null
    }
}

function Get-IntelGpuInfo {
    Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match 'Intel' } |
        ForEach-Object {
            [pscustomobject]@{
                Name = $_.Name
                DriverVersion = $_.DriverVersion
                AdapterRamBytes = $_.AdapterRAM
                VideoProcessor = $_.VideoProcessor
                PnpDeviceId = $_.PNPDeviceID
            }
        }
}

function Get-OneVplRuntimeInfo {
    $dllPaths = @(
        'C:\Windows\System32\libvpl.dll',
        'C:\Windows\System32\vpl.dll',
        'C:\Windows\System32\onevpl.dll'
    )

    foreach ($root in @('C:\Program Files\Intel', 'C:\Program Files (x86)\Intel', 'C:\Windows\System32')) {
        if (-not (Test-Path $root)) { continue }
        Get-ChildItem -Path $root -Recurse -Filter 'libvpl*.dll' -ErrorAction SilentlyContinue |
            ForEach-Object { $dllPaths += $_.FullName }
    }

    $dllPaths |
        Where-Object { $_ -and (Test-Path $_) } |
        Select-Object -Unique |
        ForEach-Object {
            $item = Get-Item $_
            [pscustomobject]@{
                Path = $item.FullName
                Version = $item.VersionInfo.FileVersion
                ProductVersion = $item.VersionInfo.ProductVersion
                SizeBytes = $item.Length
                LastWriteTime = $item.LastWriteTime
            }
        }
}

function Get-LegacyMediaSdkInfo {
    Get-ChildItem 'C:\Windows\System32\libmfx*.dll' -ErrorAction SilentlyContinue |
        ForEach-Object {
            [pscustomobject]@{
                Path = $_.FullName
                Version = $_.VersionInfo.FileVersion
                ProductVersion = $_.VersionInfo.ProductVersion
            }
        }
}

function Get-RuntimeAvailability {
    [pscustomobject]@{
        VulkanPaths = @(
            'C:\Windows\System32\vulkan-1.dll',
            'C:\Windows\System32\vulkaninfo.exe'
        ) | Where-Object { Test-Path $_ }
        OpenClPaths = @('C:\Windows\System32\OpenCL.dll') | Where-Object { Test-Path $_ }
        DxDiagNote = 'DirectX feature levels require dxdiag; this helper only checks runtime DLL presence.'
    }
}

function Test-BinarySwapState {
    param([string]$ServerDir)

    if (-not $ServerDir) {
        return [pscustomobject]@{
            BinarySwapDetected = $false
            BundledBackupExists = $false
            ActiveMatchesOverride = $false
            Note = 'Server directory unknown.'
        }
    }

    $active = Join-Path $ServerDir 'ffmpeg.exe'
    $bak = Join-Path $ServerDir 'ffmpeg.exe.bak'
    $override = 'C:\FFmpeg9\bin\ffmpeg.exe'

    $swapDetected = Test-Path $bak
    $activeMatchesOverride = $false
    if ((Test-Path $active) -and (Test-Path $override)) {
        try {
            $hashActive = (Get-FileHash $active -Algorithm SHA256).Hash
            $hashOverride = (Get-FileHash $override -Algorithm SHA256).Hash
            $activeMatchesOverride = $hashActive -eq $hashOverride
        }
        catch { }
    }

    return [pscustomobject]@{
        BinarySwapDetected = $swapDetected
        BundledBackupExists = (Test-Path $bak)
        ActiveMatchesOverride = $activeMatchesOverride
        Note = if ($swapDetected) {
            'Bundled ffmpeg.exe was replaced; prefer EncoderAppPath-only override for Jellyfin updates.'
        } else {
            'No binary swap detected.'
        }
    }
}

function Stop-JellyfinRuntime {
    param([string]$LogFile)

    Write-LogLine -Message 'Stopping Jellyfin processes and services...' -LogFile $LogFile
    Get-Service -Name 'Jellyfin*' -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Status -eq 'Running') {
            Stop-Service -Name $_.Name -Force -ErrorAction SilentlyContinue
            Write-LogLine -Message "Stopped service: $($_.Name)" -LogFile $LogFile
        }
    }
    Get-Process -Name 'jellyfin','Jellyfin.Windows.Tray' -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
        Write-LogLine -Message "Stopped process $($_.ProcessName) PID $($_.Id)" -LogFile $LogFile
    }
    Start-Sleep -Seconds 3
}

function Start-JellyfinRuntime {
    param([string]$LogFile)

    $svc = Get-Service -Name 'Jellyfin*' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($svc) {
        Start-Service -Name $svc.Name
        Write-LogLine -Message "Started service: $($svc.Name)" -LogFile $LogFile
        return
    }

    $tray = 'C:\Program Files\Jellyfin\Server\jellyfin-windows-tray\Jellyfin.Windows.Tray.exe'
    if (Test-Path $tray) {
        Start-Process -FilePath $tray | Out-Null
        Write-LogLine -Message 'Started Jellyfin tray app.' -LogFile $LogFile
        return
    }

    Write-LogLine -Message 'No Jellyfin service or tray app found; start Jellyfin manually.' -LogFile $LogFile
}

function Restore-JellyfinBundledFfmpeg {
    param(
        [string]$ServerDir,
        [string]$BackupRoot = 'C:\ProgramData\Jellyfin\backups\ffmpeg-restore'
    )

    if (-not $ServerDir) { throw 'ServerDir is required.' }

    $restored = @()
    foreach ($name in @('ffmpeg.exe', 'ffprobe.exe')) {
        $target = Join-Path $ServerDir $name
        $bak = Join-Path $ServerDir ($name + '.bak')
        if (-not (Test-Path $bak)) { continue }

        if (Test-Path $target) {
            Backup-ConfigFile -Path $target -BackupRoot $BackupRoot -Label 'pre-restore' | Out-Null
            Remove-Item $target -Force
        }

        Rename-Item -Path $bak -NewName $name -Force
        $restored += $name
    }

    return $restored
}

function Get-JellyfinRecommendedEncodingProfile {
    param(
        [string]$FfmpegOverridePath = 'C:\FFmpeg9\bin\ffmpeg.exe',
        [string]$GpuName = $null,
        [object]$Hardware = $null,
        [object]$EncoderCaps = $null
    )

    if (-not (Get-Command Get-JellyfinAutoEncodingProfile -ErrorAction SilentlyContinue)) {
        $isArc = $GpuName -match 'Arc'
        return [pscustomobject][ordered]@{
            EncoderAppPath = $FfmpegOverridePath
            EncoderAppPathDisplay = $FfmpegOverridePath
            HardwareAccelerationType = 'qsv'
            EnableVppTonemapping = 'true'
            AllowAv1Encoding = if ($isArc -and $GpuName -notmatch 'A310|A350|A370|A380') { 'true' } else { 'false' }
            Rationale = @('Legacy profile fallback; load Hardware-Tuning.ps1 for full detection.')
        }
    }

    return Get-JellyfinAutoEncodingProfile -FfmpegOverridePath $FfmpegOverridePath -Hardware $Hardware -EncoderCaps $EncoderCaps
}

function Set-XmlNodeText {
    param(
        [xml]$Xml,
        [System.Xml.XmlElement]$Root,
        [string]$NodeName,
        [string]$Value
    )

    $node = $Root.SelectSingleNode($NodeName)
    if (-not $node) {
        $node = $Xml.CreateElement($NodeName)
        [void]$Root.AppendChild($node)
    }
    $node.InnerText = $Value
}

function Set-XmlStringList {
    param(
        [xml]$Xml,
        [System.Xml.XmlElement]$Root,
        [string]$NodeName,
        [string[]]$Values
    )

    $parent = $Root.SelectSingleNode($NodeName)
    if (-not $parent) {
        $parent = $Xml.CreateElement($NodeName)
        [void]$Root.AppendChild($parent)
    }

    $parent.RemoveAll()
    foreach ($value in ($Values | Select-Object -Unique)) {
        $el = $Xml.CreateElement('string')
        $el.InnerText = $value
        [void]$parent.AppendChild($el)
    }
}

function Apply-JellyfinEncodingProfile {
    param(
        [string]$EncodingXmlPath,
        [hashtable]$Profile,
        [string]$BackupRoot = 'C:\ProgramData\Jellyfin\backups\encoding-optimize'
    )

    if (-not (Test-Path $EncodingXmlPath)) {
        throw "encoding.xml not found: $EncodingXmlPath"
    }

    $backup = Backup-ConfigFile -Path $EncodingXmlPath -BackupRoot $BackupRoot -Label 'encoding'
    [xml]$xml = Get-Content -Path $EncodingXmlPath -Encoding UTF8
    $root = $xml.EncodingOptions

    $scalarKeys = @(
        'EncoderAppPath', 'EncoderAppPathDisplay', 'HardwareAccelerationType', 'QsvDevice',
        'EnableHardwareEncoding', 'EnableTonemapping', 'EnableVppTonemapping', 'EnableVideoToolboxTonemapping',
        'TonemappingAlgorithm', 'TonemappingMode', 'TonemappingRange', 'TonemappingDesat', 'TonemappingPeak',
        'TonemappingParam', 'VppTonemappingBrightness', 'VppTonemappingContrast', 'PreferSystemNativeHwDecoder',
        'EnableDecodingColorDepth10Hevc', 'EnableDecodingColorDepth10Vp9', 'EnableDecodingColorDepth10HevcRext',
        'EnableDecodingColorDepth12HevcRext', 'EnableEnhancedNvdecDecoder', 'EnableIntelLowPowerH264HwEncoder',
        'EnableIntelLowPowerHevcHwEncoder', 'AllowHevcEncoding', 'AllowAv1Encoding', 'EnableSubtitleExtraction',
        'EncodingThreadCount', 'MaxMuxingQueueSize', 'EnableThrottling', 'ThrottleDelaySeconds',
        'EnableSegmentDeletion', 'SegmentKeepSeconds', 'DeinterlaceMethod', 'DeinterlaceDoubleRate',
        'H264Crf', 'H265Crf'
    )

    foreach ($key in $scalarKeys) {
        if ($Profile.ContainsKey($key)) {
            Set-XmlNodeText -Xml $xml -Root $root -NodeName $key -Value ([string]$Profile[$key])
        }
    }

    if ($Profile.ContainsKey('HardwareDecodingCodecs')) {
        Set-XmlStringList -Xml $xml -Root $root -NodeName 'HardwareDecodingCodecs' -Values $Profile.HardwareDecodingCodecs
    }

    if ($Profile.ContainsKey('AllowOnDemandMetadataBasedKeyframeExtractionForExtensions')) {
        Set-XmlStringList -Xml $xml -Root $root -NodeName 'AllowOnDemandMetadataBasedKeyframeExtractionForExtensions' -Values $Profile.AllowOnDemandMetadataBasedKeyframeExtractionForExtensions
    }

    $xml.Save($EncodingXmlPath)

    return [pscustomobject]@{
        EncodingXmlPath = $EncodingXmlPath
        BackupPath = $backup
        AppliedKeys = @($Profile.Keys)
    }
}

function Export-MarkdownSection {
    param(
        [System.Text.StringBuilder]$Builder,
        [string]$Title,
        [int]$Level = 2
    )
    $hash = '#' * $Level
    [void]$Builder.AppendLine('')
    [void]$Builder.AppendLine("$hash $Title")
    [void]$Builder.AppendLine('')
}

function Export-MarkdownTable {
    param(
        [System.Text.StringBuilder]$Builder,
        [object[]]$Rows,
        [string[]]$Columns
    )

    if (-not $Rows -or $Rows.Count -eq 0) {
        [void]$Builder.AppendLine('_No data._')
        return
    }

    [void]$Builder.AppendLine(('| ' + ($Columns -join ' | ') + ' |'))
    [void]$Builder.AppendLine(('| ' + (($Columns | ForEach-Object { '---' }) -join ' | ') + ' |'))
    foreach ($row in $Rows) {
        $cells = foreach ($col in $Columns) {
            $value = $row.$col
            if ($null -eq $value) { '' }
            elseif ($value -is [array]) { ($value -join ', ') }
            else { [string]$value }
        }
        [void]$Builder.AppendLine(('| ' + ($cells -join ' | ') + ' |'))
    }
}

function Get-PerformanceSample {
    param([int]$ProcessId = 0)

    $sample = [ordered]@{
        Timestamp = Get-Date
        CpuTotalPct = $null
        ProcessCpuPct = $null
        ProcessWorkingSetMb = $null
        ProcessThreads = $null
        GpuEngines = @()
        Error = $null
    }

    try {
        $cpu = Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction Stop
        $sample.CpuTotalPct = [math]::Round($cpu.CounterSamples[0].CookedValue, 2)
    }
    catch {
        $sample.Error = $_.Exception.Message
    }

    if ($ProcessId -gt 0) {
        $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
        if ($proc) {
            $sample.ProcessWorkingSetMb = [math]::Round($proc.WorkingSet64 / 1MB, 2)
            $sample.ProcessThreads = $proc.Threads.Count
            try {
                $procCpu = Get-Counter ("\Process($($proc.ProcessName))\% Processor Time") -ErrorAction Stop
                $sample.ProcessCpuPct = [math]::Round($procCpu.CounterSamples[0].CookedValue, 2)
            }
            catch { }
        }
    }

    try {
        $gpuCounters = Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction Stop
        foreach ($counterSample in $gpuCounters.CounterSamples) {
            if ($counterSample.CookedValue -le 0.01) { continue }
            $sample.GpuEngines += [pscustomobject]@{
                Instance = $counterSample.InstanceName
                UtilizationPct = [math]::Round($counterSample.CookedValue, 2)
            }
        }
    }
    catch { }

    return [pscustomobject]$sample
}

function Get-EncodingXmlSummary {
    param([string]$EncodingXmlPath)

    $xml = Import-XmlFileSafe -Path $EncodingXmlPath
    if (-not $xml) { return $null }

    $root = $xml.EncodingOptions
    $codecs = @($root.HardwareDecodingCodecs.string)

    return [pscustomobject]@{
        HardwareAccelerationType = [string]$root.HardwareAccelerationType
        EncoderAppPath = [string]$root.EncoderAppPath
        EnableHardwareEncoding = [string]$root.EnableHardwareEncoding
        EnableTonemapping = [string]$root.EnableTonemapping
        EnableVppTonemapping = [string]$root.EnableVppTonemapping
        PreferSystemNativeHwDecoder = [string]$root.PreferSystemNativeHwDecoder
        AllowAv1Encoding = [string]$root.AllowAv1Encoding
        EncodingThreadCount = [string]$root.EncodingThreadCount
        HardwareDecodingCodecs = $codecs
    }
}

function Get-FfmpegVersionQuick {
    param([string]$FfmpegPath)

    if (-not (Test-Path $FfmpegPath)) {
        return $null
    }

    $result = Get-SafeCommandOutput -FilePath $FfmpegPath -Arguments @('-version') -TimeoutSeconds 20
    if ($result.Error -or $result.ExitCode -ne 0) {
        return $null
    }

    $line = (($result.StdOut + $result.StdErr) -split "`r?`n" | Where-Object { $_ -match '^ffmpeg version' } | Select-Object -First 1)
    if (-not $line) { return $null }

    if ($line -match 'ffmpeg version (\S+)') {
        return $Matches[1]
    }

    return $line
}

function Test-JellyfinFfmpeg9BinaryReady {
    param([string]$FfmpegPath = 'C:\FFmpeg9\bin\ffmpeg.exe')

    if (-not (Test-Path $FfmpegPath)) {
        return $false
    }

    $version = Get-FfmpegVersionQuick -FfmpegPath $FfmpegPath
    return [bool]($version -and ($version -match '^9(\.|$|-)'))
}

function Test-JellyfinFfmpeg9PatchActive {
    param(
        [string]$FfmpegPath = 'C:\FFmpeg9\bin\ffmpeg.exe',
        [object]$Encoding = $null
    )

    if (-not (Test-JellyfinFfmpeg9BinaryReady -FfmpegPath $FfmpegPath)) {
        return $false
    }

    if (-not $Encoding) {
        $layout = Get-JellyfinLayout
        if (-not $layout) { return $false }
        $encodingPath = Join-Path $layout.ConfigDir 'encoding.xml'
        $Encoding = Get-EncodingXmlSummary -EncodingXmlPath $encodingPath
    }

    if (-not $Encoding) { return $false }

    $configuredPath = [string]$Encoding.EncoderAppPath
    if ([string]::IsNullOrWhiteSpace($configuredPath)) { return $false }

    return ($configuredPath -eq $FfmpegPath)
}

function Test-JellyfinFfmpeg9PatchConfigured {
    param(
        [string]$FfmpegPath = 'C:\FFmpeg9\bin\ffmpeg.exe',
        [string]$ProgramRoot = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9',
        [object]$Encoding = $null
    )

    if (-not (Test-JellyfinFfmpeg9BinaryReady -FfmpegPath $FfmpegPath)) {
        return $false
    }

    if (Get-Command Get-ProgramUserConfig -ErrorAction SilentlyContinue) {
        $userConfig = Get-ProgramUserConfig -ProgramRoot $ProgramRoot
        if ($userConfig.applied_at) {
            return $true
        }
    }

    return (Test-JellyfinFfmpeg9PatchActive -FfmpegPath $FfmpegPath -Encoding $Encoding)
}

function Get-JellyfinFfmpeg9Status {
    param(
        [string]$FfmpegPath = 'C:\FFmpeg9\bin\ffmpeg.exe',
        [string]$ProgramRoot = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9'
    )

    $layout = Get-JellyfinLayout
    $encodingPath = if ($layout) { Join-Path $layout.ConfigDir 'encoding.xml' } else { $null }
    $encoding = if ($encodingPath) { Get-EncodingXmlSummary -EncodingXmlPath $encodingPath } else { $null }
    $swap = if ($layout -and $layout.ServerDir) { Test-BinarySwapState -ServerDir $layout.ServerDir } else { $null }

    $userConfig = if (Get-Command Get-ProgramUserConfig -ErrorAction SilentlyContinue) {
        Get-ProgramUserConfig -ProgramRoot $ProgramRoot
    } else {
        [pscustomobject]@{ profile_mode = 'auto'; hardware_snapshot = $null }
    }
    $profileMode = if ($userConfig.profile_mode) { [string]$userConfig.profile_mode } else { 'auto' }
    $savedSnapshot = $userConfig.hardware_snapshot

    $expected = if (Get-Command Get-ExpectedEncodingChecks -ErrorAction SilentlyContinue) {
        Get-ExpectedEncodingChecks -ProfileMode $profileMode -FfmpegPath $FfmpegPath -SavedSnapshot $savedSnapshot
    } else {
        [pscustomobject]@{ RequireEncoderPath = $true; RequireHardwareAccelerationType = 'qsv'; RequireVppTonemapping = 'true' }
    }

    $ffprobePath = Join-Path (Split-Path -Parent $FfmpegPath) 'ffprobe.exe'
    $version = Get-FfmpegVersionQuick -FfmpegPath $FfmpegPath
    $issues = [System.Collections.Generic.List[string]]::new()

    if (-not (Test-Path $FfmpegPath)) {
        $issues.Add('ffmpeg9_missing')
    }
    elseif (-not $version -or ($version -notmatch '^9(\.|$|-)')) {
        $issues.Add('ffmpeg9_version_mismatch')
    }

    if (-not (Test-Path $ffprobePath)) {
        $issues.Add('ffprobe_missing')
    }

    if (-not $encoding) {
        $issues.Add('encoding_xml_missing')
    }
    else {
        $configured = [string]$encoding.EncoderAppPath
        if ($configured -ne $FfmpegPath) {
            $issues.Add('encoder_path_mismatch')
        }

        if ($profileMode -ne 'manual' -and $expected.RequireHardwareAccelerationType) {
            $expectedHw = [string]$expected.RequireHardwareAccelerationType
            $actualHw = [string]$encoding.HardwareAccelerationType
            if ($expectedHw -ne 'none' -and $actualHw -ne $expectedHw) {
                $issues.Add('hw_accel_mismatch')
            }
            if ($expected.RequireVppTonemapping -and [string]$encoding.EnableVppTonemapping -ne $expected.RequireVppTonemapping) {
                $issues.Add('vpp_tonemap_mismatch')
            }
        }
    }

    if ($swap -and $swap.BinarySwapDetected) {
        $issues.Add('binary_swap_detected')
    }

    $critical = @('ffmpeg9_missing', 'ffmpeg9_version_mismatch', 'encoding_xml_missing', 'encoder_path_mismatch')
    $status = 'ok'
    if ($issues | Where-Object { $_ -in $critical }) {
        $status = 'alert'
    }
    elseif ($issues.Count -gt 0) {
        $status = 'warn'
    }

    $modeLabel = if ($profileMode -eq 'manual') { 'manual FFmpeg path' } else { 'auto-tuned' }
    $patchActive = Test-JellyfinFfmpeg9PatchActive -FfmpegPath $FfmpegPath -Encoding $encoding
    $patchConfigured = Test-JellyfinFfmpeg9PatchConfigured -FfmpegPath $FfmpegPath -ProgramRoot $ProgramRoot -Encoding $encoding
    $message = switch ($status) {
        'ok' {
            if ($patchActive) {
                "FFmpeg 9 patch active ($modeLabel); config preserved at $FfmpegPath"
            }
            else {
                "FFmpeg 9 configured ($modeLabel) at $FfmpegPath"
            }
        }
        'alert' {
            $preview = ($issues | Select-Object -First 3) -join ', '
            "FFmpeg 9 needs repair: $preview"
        }
        default {
            $preview = ($issues | Select-Object -First 3) -join ', '
            "FFmpeg 9 drift ($modeLabel): $preview"
        }
    }

    return [ordered]@{
        status = $status
        message = $message
        profile_mode = $profileMode
        patch_active = $patchActive
        patch_configured = $patchConfigured
        ffmpeg_path = $FfmpegPath
        ffmpeg_version = $version
        encoder_app_path = if ($encoding) { $encoding.EncoderAppPath } else { $null }
        hardware_acceleration = if ($encoding) { $encoding.HardwareAccelerationType } else { $null }
        expected_hardware_acceleration = $expected.RequireHardwareAccelerationType
        binary_swap_detected = if ($swap) { $swap.BinarySwapDetected } else { $false }
        issues = @($issues)
        repair_script = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9\Install-JellyfinFfmpeg9.ps1'
    }
}
