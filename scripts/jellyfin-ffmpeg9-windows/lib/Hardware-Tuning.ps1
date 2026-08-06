Set-StrictMode -Version Latest

function Get-ProgramUserConfigPath {
    param([string]$ProgramRoot = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9')
    Join-Path $ProgramRoot 'user.config.json'
}

function Get-ProgramUserConfig {
    param([string]$ProgramRoot = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9')

    $path = Get-ProgramUserConfigPath -ProgramRoot $ProgramRoot
    if (-not (Test-Path $path)) {
        return [ordered]@{
            profile_mode = 'auto'
            hardware_snapshot = $null
            applied_at = $null
        }
    }

    try {
        return (Get-Content -Path $path -Raw -Encoding UTF8 | ConvertFrom-Json)
    }
    catch {
        return [ordered]@{ profile_mode = 'auto'; hardware_snapshot = $null; applied_at = $null }
    }
}

function Save-ProgramUserConfig {
    param(
        [string]$ProgramRoot,
        [string]$ProfileMode,
        [object]$HardwareSnapshot
    )

    New-Item -ItemType Directory -Force -Path $ProgramRoot | Out-Null
    $payload = [ordered]@{
        profile_mode = $ProfileMode
        hardware_snapshot = $HardwareSnapshot
        applied_at = (Get-Date -Format o)
    }
    $payload | ConvertTo-Json -Depth 6 | Set-Content -Path (Get-ProgramUserConfigPath -ProgramRoot $ProgramRoot) -Encoding UTF8
}

function Get-SystemMediaHardware {
    $cpu = Get-CimInstance Win32_Processor -ErrorAction SilentlyContinue | Select-Object -First 1
    $gpus = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Where-Object {
            $_.PSObject.Properties['Name'] -and -not [string]::IsNullOrWhiteSpace([string]$_.Name)
        })

    $toGpuInfo = {
        param($Gpu)
        $gpuName = if ($Gpu.PSObject.Properties['Name']) { [string]$Gpu.Name } else { 'Unknown GPU' }
        [pscustomobject]@{
            Name = $gpuName
            DriverVersion = if ($Gpu.PSObject.Properties['DriverVersion']) { [string]$Gpu.DriverVersion } else { $null }
        }
    }

    $intel = @($gpus | Where-Object { $_.PSObject.Properties['Name'] -and [string]$_.Name -match 'Intel' })
    $nvidia = @($gpus | Where-Object { $_.PSObject.Properties['Name'] -and [string]$_.Name -match 'NVIDIA|GeForce|RTX|GTX|Quadro' })
    $amd = @($gpus | Where-Object { $_.PSObject.Properties['Name'] -and [string]$_.Name -match 'AMD|Radeon' })

    $logicalCores = [Environment]::ProcessorCount
    $physicalCores = if ($cpu -and $cpu.PSObject.Properties['NumberOfCores'] -and $cpu.NumberOfCores) { [int]$cpu.NumberOfCores } else { $logicalCores }
    $cpuName = if ($cpu -and $cpu.PSObject.Properties['Name']) { [string]$cpu.Name } else { 'Unknown CPU' }

    return [pscustomobject]@{
        CpuName = $cpuName
        PhysicalCores = $physicalCores
        LogicalCores = $logicalCores
        IntelGpus = @($intel | ForEach-Object { & $toGpuInfo $_ })
        NvidiaGpus = @($nvidia | ForEach-Object { & $toGpuInfo $_ })
        AmdGpus = @($amd | ForEach-Object { & $toGpuInfo $_ })
        PrimaryIntelGpu = if ($intel.Count -gt 0) { [string]$intel[0].Name } else { $null }
        PrimaryNvidiaGpu = if ($nvidia.Count -gt 0) { [string]$nvidia[0].Name } else { $null }
        PrimaryAmdGpu = if ($amd.Count -gt 0) { [string]$amd[0].Name } else { $null }
    }
}

function Get-FfmpegEncoderCapabilities {
    param([string]$FfmpegPath)

    $caps = [ordered]@{
        Path = $FfmpegPath
        Qsv = @()
        Nvenc = @()
        Amf = @()
        Vaapi = @()
        Available = $false
    }

    if (-not (Test-Path $FfmpegPath)) {
        return [pscustomobject]$caps
    }

    $output = & $FfmpegPath -hide_banner -encoders 2>&1
    if (-not $output) {
        return [pscustomobject]$caps
    }

    $caps.Available = $true
    foreach ($line in ($output -split "`r?`n")) {
        if ($line -match '\s([a-z0-9_]+_qsv)\s') { $caps.Qsv += $Matches[1] }
        if ($line -match '\s([a-z0-9_]+_nvenc)\s') { $caps.Nvenc += $Matches[1] }
        if ($line -match '\s([a-z0-9_]+_amf)\s') { $caps.Amf += $Matches[1] }
        if ($line -match '\s([a-z0-9_]+_vaapi)\s') { $caps.Vaapi += $Matches[1] }
    }

    $caps.Qsv = @($caps.Qsv | Select-Object -Unique)
    $caps.Nvenc = @($caps.Nvenc | Select-Object -Unique)
    $caps.Amf = @($caps.Amf | Select-Object -Unique)
    $caps.Vaapi = @($caps.Vaapi | Select-Object -Unique)

    return [pscustomobject]$caps
}

function Select-JellyfinHardwareAcceleration {
    param(
        [object]$Hardware,
        [object]$EncoderCaps
    )

    $rationale = [System.Collections.Generic.List[string]]::new()
    $choice = [ordered]@{
        HardwareAccelerationType = 'none'
        EnableHardwareEncoding = 'false'
        EnableVppTonemapping = 'false'
        EnableEnhancedNvdecDecoder = 'true'
        PreferSystemNativeHwDecoder = 'true'
        AllowAv1Encoding = 'false'
        EnableIntelLowPowerH264HwEncoder = 'false'
        EnableIntelLowPowerHevcHwEncoder = 'false'
        SelectedVendor = 'software'
        SelectedGpu = $null
    }

    $hasQsv = $EncoderCaps.Qsv.Count -gt 0 -and $Hardware.IntelGpus.Count -gt 0
    $hasNvenc = $EncoderCaps.Nvenc.Count -gt 0 -and $Hardware.NvidiaGpus.Count -gt 0
    $hasAmf = $EncoderCaps.Amf.Count -gt 0 -and $Hardware.AmdGpus.Count -gt 0

    if ($hasQsv) {
        $gpu = $Hardware.PrimaryIntelGpu
        $choice.HardwareAccelerationType = 'qsv'
        $choice.EnableHardwareEncoding = 'true'
        $choice.EnableVppTonemapping = 'true'
        $choice.SelectedVendor = 'intel'
        $choice.SelectedGpu = $gpu
        [void]$rationale.Add("Intel GPU detected ($gpu) with FFmpeg QSV encoders.")

        if ($gpu -match 'Arc' -or ($EncoderCaps.Qsv -contains 'av1_qsv')) {
            $choice.AllowAv1Encoding = 'true'
            [void]$rationale.Add('AV1 hardware encode enabled (Intel Arc / av1_qsv available).')
        }

        if ($gpu -match 'UHD|Iris' -and $gpu -notmatch 'Arc') {
            [void]$rationale.Add('Intel iGPU without Arc: VPP tonemapping enabled; AV1 encode left conservative.')
        }
    }
    elseif ($hasNvenc) {
        $gpu = $Hardware.PrimaryNvidiaGpu
        $choice.HardwareAccelerationType = 'nvenc'
        $choice.EnableHardwareEncoding = 'true'
        $choice.EnableVppTonemapping = 'false'
        $choice.EnableEnhancedNvdecDecoder = 'true'
        $choice.SelectedVendor = 'nvidia'
        $choice.SelectedGpu = $gpu
        [void]$rationale.Add("NVIDIA GPU detected ($gpu) with FFmpeg NVENC encoders.")

        if ($EncoderCaps.Nvenc -contains 'av1_nvenc') {
            $choice.AllowAv1Encoding = 'true'
            [void]$rationale.Add('AV1 hardware encode enabled (av1_nvenc available).')
        }
    }
    elseif ($hasAmf) {
        $gpu = $Hardware.PrimaryAmdGpu
        $choice.HardwareAccelerationType = 'amf'
        $choice.EnableHardwareEncoding = 'true'
        $choice.EnableVppTonemapping = 'false'
        $choice.SelectedVendor = 'amd'
        $choice.SelectedGpu = $gpu
        [void]$rationale.Add("AMD GPU detected ($gpu) with FFmpeg AMF encoders.")

        if ($EncoderCaps.Amf -contains 'av1_amf') {
            $choice.AllowAv1Encoding = 'true'
            [void]$rationale.Add('AV1 hardware encode enabled (av1_amf available).')
        }
    }
    else {
        [void]$rationale.Add('No usable hardware encoders detected in FFmpeg; software transcoding fallback.')
        [void]$rationale.Add('EncoderAppPath still points at FFmpeg 9 for Jellyfin compatibility.')
    }

    if ($Hardware.LogicalCores -ge 8) {
        [void]$rationale.Add("CPU $($Hardware.CpuName) ($($Hardware.LogicalCores) threads): EncodingThreadCount=0 (Jellyfin auto).")
    }
    else {
        [void]$rationale.Add("CPU $($Hardware.CpuName): EncodingThreadCount=0.")
    }

    return [pscustomobject]@{
        Choice = [pscustomobject]$choice
        Rationale = @($rationale)
        Hardware = $Hardware
        EncoderCaps = $EncoderCaps
    }
}

function Get-JellyfinAutoEncodingProfile {
    param(
        [string]$FfmpegOverridePath = 'C:\FFmpeg9\bin\ffmpeg.exe',
        [object]$Hardware = $null,
        [object]$EncoderCaps = $null
    )

    if (-not $Hardware) { $Hardware = Get-SystemMediaHardware }
    if (-not $EncoderCaps) { $EncoderCaps = Get-FfmpegEncoderCapabilities -FfmpegPath $FfmpegOverridePath }

    $plan = Select-JellyfinHardwareAcceleration -Hardware $Hardware -EncoderCaps $EncoderCaps
    $accel = $plan.Choice

    $profile = [ordered]@{
        EncoderAppPath = $FfmpegOverridePath
        EncoderAppPathDisplay = $FfmpegOverridePath
        HardwareAccelerationType = $accel.HardwareAccelerationType
        QsvDevice = ''
        EnableHardwareEncoding = $accel.EnableHardwareEncoding
        EnableTonemapping = 'true'
        EnableVppTonemapping = $accel.EnableVppTonemapping
        EnableVideoToolboxTonemapping = 'false'
        TonemappingAlgorithm = 'bt2390'
        TonemappingMode = 'auto'
        TonemappingRange = 'auto'
        TonemappingDesat = '0'
        TonemappingPeak = '100'
        TonemappingParam = '0'
        VppTonemappingBrightness = '16'
        VppTonemappingContrast = '1'
        PreferSystemNativeHwDecoder = $accel.PreferSystemNativeHwDecoder
        EnableDecodingColorDepth10Hevc = 'true'
        EnableDecodingColorDepth10Vp9 = 'true'
        EnableDecodingColorDepth10HevcRext = 'false'
        EnableDecodingColorDepth12HevcRext = 'false'
        EnableEnhancedNvdecDecoder = $accel.EnableEnhancedNvdecDecoder
        EnableIntelLowPowerH264HwEncoder = $accel.EnableIntelLowPowerH264HwEncoder
        EnableIntelLowPowerHevcHwEncoder = $accel.EnableIntelLowPowerHevcHwEncoder
        AllowHevcEncoding = if ($accel.EnableHardwareEncoding -eq 'true') { 'true' } else { 'false' }
        AllowAv1Encoding = $accel.AllowAv1Encoding
        EnableSubtitleExtraction = 'true'
        EncodingThreadCount = '0'
        MaxMuxingQueueSize = '2048'
        EnableThrottling = 'true'
        ThrottleDelaySeconds = '90'
        EnableSegmentDeletion = 'true'
        SegmentKeepSeconds = '90'
        DeinterlaceMethod = 'yadif'
        DeinterlaceDoubleRate = 'false'
        H264Crf = '23'
        H265Crf = '28'
        HardwareDecodingCodecs = @('h264', 'hevc', 'av1', 'vc1', 'mpeg2video')
        AllowOnDemandMetadataBasedKeyframeExtractionForExtensions = @('mkv')
        Rationale = @($plan.Rationale)
        TuningPlan = $plan
    }

    return [pscustomobject]$profile
}

function Get-JellyfinManualEncodingProfile {
    param([string]$FfmpegOverridePath = 'C:\FFmpeg9\bin\ffmpeg.exe')

    return [pscustomobject][ordered]@{
        EncoderAppPath = $FfmpegOverridePath
        EncoderAppPathDisplay = $FfmpegOverridePath
        Rationale = @(
            'Manual/default mode: only the custom FFmpeg path is applied.'
            'Existing Jellyfin Dashboard transcoding settings are left unchanged.'
            'Tune hardware acceleration yourself under Dashboard -> Playback -> Transcoding.'
        )
    }
}

function Convert-ProfileObjectToHashtable {
    param([object]$ProfileObject)

    $profile = @{}
    foreach ($prop in $ProfileObject.PSObject.Properties) {
        if ($prop.Name -notin @('Rationale', 'TuningPlan')) {
            $profile[$prop.Name] = $prop.Value
        }
    }
    return $profile
}

function Show-HardwareTuningSummary {
    param(
        [object]$Hardware,
        [object]$Plan,
        [string]$ProfileMode
    )

    Write-Host ''
    Write-Host '=== Detected hardware ===' -ForegroundColor Cyan
    Write-Host "CPU: $($Hardware.CpuName) ($($Hardware.PhysicalCores)c / $($Hardware.LogicalCores)t)"
    if ($Hardware.IntelGpus.Count -gt 0) {
        Write-Host ("Intel GPU: " + (($Hardware.IntelGpus | ForEach-Object { $_.Name }) -join '; '))
    }
    if ($Hardware.NvidiaGpus.Count -gt 0) {
        Write-Host ("NVIDIA GPU: " + (($Hardware.NvidiaGpus | ForEach-Object { $_.Name }) -join '; '))
    }
    if ($Hardware.AmdGpus.Count -gt 0) {
        Write-Host ("AMD GPU: " + (($Hardware.AmdGpus | ForEach-Object { $_.Name }) -join '; '))
    }

    Write-Host ''
    Write-Host "Config mode: $ProfileMode" -ForegroundColor Cyan
    if ($ProfileMode -eq 'auto' -and $Plan) {
        Write-Host ("Recommended acceleration: {0} ({1})" -f $Plan.Choice.HardwareAccelerationType, $Plan.Choice.SelectedGpu)
        foreach ($line in $Plan.Rationale) {
            Write-Host "  - $line"
        }
    }
    else {
        Write-Host 'Only FFmpeg path will be configured; Jellyfin transcoding settings stay manual.'
    }
    Write-Host ''
}

function Resolve-JellyfinConfigMode {
    param(
        [switch]$AutoTune,
        [switch]$ManualConfig,
        [switch]$Interactive,
        [switch]$Quiet,
        [object]$Hardware = $null,
        [object]$EncoderCaps = $null,
        [string]$FfmpegPath = 'C:\FFmpeg9\bin\ffmpeg.exe'
    )

    if ($ManualConfig) { return 'manual' }
    if ($AutoTune) { return 'auto' }

    if ($Interactive -and -not $Quiet) {
        if (-not $Hardware) { $Hardware = Get-SystemMediaHardware }
        if (-not $EncoderCaps) { $EncoderCaps = Get-FfmpegEncoderCapabilities -FfmpegPath $FfmpegPath }
        $plan = Select-JellyfinHardwareAcceleration -Hardware $Hardware -EncoderCaps $EncoderCaps

        Show-HardwareTuningSummary -Hardware $Hardware -Plan $plan -ProfileMode 'auto'

        Write-Host 'Apply automatic transcoding tuning based on detected CPU/GPU?' -ForegroundColor Yellow
        Write-Host '  Y = auto-tune encoding.xml for your hardware (recommended)'
        Write-Host '  N = manual/default (set FFmpeg path only; keep your Dashboard settings)'
        $answer = Read-Host 'Choice [Y/n]'
        if ($answer -match '^(n|no)$') {
            return 'manual'
        }
    }

    return 'auto'
}

function Resolve-JellyfinProfileModeForAction {
    param(
        [string]$Action,
        [switch]$AutoTune,
        [switch]$ManualConfig,
        [switch]$Interactive,
        [switch]$Quiet,
        [string]$FfmpegPath = 'C:\FFmpeg9\bin\ffmpeg.exe',
        [string]$ProgramRoot = 'C:\ProgramData\Jellyfin\scripts\jellyfin-ffmpeg9',
        [object]$SavedConfig = $null
    )

    if ($ManualConfig) { return 'manual' }
    if ($AutoTune) { return 'auto' }

    if (-not $SavedConfig) {
        $SavedConfig = Get-ProgramUserConfig -ProgramRoot $ProgramRoot
    }

    if ($SavedConfig.profile_mode) {
        return [string]$SavedConfig.profile_mode
    }

    $patchConfigured = Test-JellyfinFfmpeg9PatchConfigured -FfmpegPath $FfmpegPath -ProgramRoot $ProgramRoot
    if ($patchConfigured -and ($Action -eq 'Repair' -or ($Action -eq 'Install' -and -not $Interactive))) {
        return 'auto'
    }

    if ($patchConfigured -and $Action -eq 'Install') {
        $layout = Get-JellyfinLayout
        if ($layout) {
            $encodingPath = Join-Path $layout.ConfigDir 'encoding.xml'
            $encoding = Get-EncodingXmlSummary -EncodingXmlPath $encodingPath
            if ($encoding -and [string]$encoding.EncoderAppPath -eq $FfmpegPath) {
                $expected = Get-ExpectedEncodingChecks -ProfileMode 'auto' -FfmpegPath $FfmpegPath
                $actualHw = [string]$encoding.HardwareAccelerationType
                if ($expected.RequireHardwareAccelerationType -and $actualHw -eq [string]$expected.RequireHardwareAccelerationType) {
                    return 'auto'
                }
                if (-not [string]::IsNullOrWhiteSpace($actualHw) -and $actualHw -ne 'none') {
                    return 'manual'
                }
            }
        }

        Write-Host 'Existing FFmpeg 9 patch detected; preserving saved transcoding settings.' -ForegroundColor Cyan
        return 'manual'
    }

    return Resolve-JellyfinConfigMode -AutoTune:$AutoTune -ManualConfig:$ManualConfig -Interactive:$Interactive -Quiet:$Quiet -FfmpegPath $FfmpegPath
}

function Get-JellyfinEncodingRepairProfile {
    param(
        [string[]]$Issues,
        [string]$ProfileMode,
        [string]$FfmpegOverridePath = 'C:\FFmpeg9\bin\ffmpeg.exe',
        [object]$Hardware = $null,
        [object]$EncoderCaps = $null,
        [switch]$FullApply
    )

    $fullProfileObject = Get-JellyfinEncodingProfileForMode -ProfileMode $ProfileMode -FfmpegOverridePath $FfmpegOverridePath -Hardware $Hardware -EncoderCaps $EncoderCaps
    $fullProfile = Convert-ProfileObjectToHashtable -ProfileObject $fullProfileObject

    if ($FullApply -or ($Issues -contains 'encoding_xml_missing')) {
        return [pscustomobject]@{
            Profile = $fullProfile
            ApplyMode = 'full'
        }
    }

    $repair = @{}
    if ($Issues -contains 'encoder_path_mismatch') {
        $repair.EncoderAppPath = $FfmpegOverridePath
        $repair.EncoderAppPathDisplay = $FfmpegOverridePath
    }

    if ($ProfileMode -eq 'auto') {
        if ($Issues -contains 'hw_accel_mismatch') {
            foreach ($key in @(
                    'HardwareAccelerationType', 'EnableHardwareEncoding', 'EnableEnhancedNvdecDecoder',
                    'PreferSystemNativeHwDecoder', 'AllowHevcEncoding', 'AllowAv1Encoding',
                    'EnableIntelLowPowerH264HwEncoder', 'EnableIntelLowPowerHevcHwEncoder')) {
                if ($fullProfile.ContainsKey($key)) {
                    $repair[$key] = $fullProfile[$key]
                }
            }
        }

        if ($Issues -contains 'vpp_tonemap_mismatch') {
            foreach ($key in @('EnableVppTonemapping', 'EnableTonemapping')) {
                if ($fullProfile.ContainsKey($key)) {
                    $repair[$key] = $fullProfile[$key]
                }
            }
        }
    }

    return [pscustomobject]@{
        Profile = $repair
        ApplyMode = if ($repair.Count -gt 0) { 'surgical' } else { 'none' }
    }
}

function Get-JellyfinEncodingProfileForMode {
    param(
        [string]$ProfileMode,
        [string]$FfmpegOverridePath = 'C:\FFmpeg9\bin\ffmpeg.exe',
        [object]$Hardware = $null,
        [object]$EncoderCaps = $null
    )

    if ($ProfileMode -eq 'manual') {
        return Get-JellyfinManualEncodingProfile -FfmpegOverridePath $FfmpegOverridePath
    }

    return Get-JellyfinAutoEncodingProfile -FfmpegOverridePath $FfmpegOverridePath -Hardware $Hardware -EncoderCaps $EncoderCaps
}

function Get-ExpectedEncodingChecks {
    param(
        [string]$ProfileMode,
        [string]$FfmpegPath,
        [object]$SavedSnapshot = $null
    )

    $checks = [ordered]@{
        RequireEncoderPath = $true
        RequireHardwareAccelerationType = $null
        RequireVppTonemapping = $null
    }

    if ($ProfileMode -eq 'manual') {
        return [pscustomobject]$checks
    }

    if ($SavedSnapshot -and $SavedSnapshot.expected_hw_accel) {
        $checks.RequireHardwareAccelerationType = [string]$SavedSnapshot.expected_hw_accel
        $checks.RequireVppTonemapping = if ($SavedSnapshot.expected_hw_accel -eq 'qsv') { 'true' } else { 'false' }
        return [pscustomobject]$checks
    }

    if (-not (Test-Path $FfmpegPath)) {
        return [pscustomobject]$checks
    }

    $hardware = Get-SystemMediaHardware
    $caps = Get-FfmpegEncoderCapabilities -FfmpegPath $FfmpegPath
    $plan = Select-JellyfinHardwareAcceleration -Hardware $hardware -EncoderCaps $caps
    $checks.RequireHardwareAccelerationType = $plan.Choice.HardwareAccelerationType
    if ($plan.Choice.HardwareAccelerationType -eq 'qsv') {
        $checks.RequireVppTonemapping = 'true'
    }

    return [pscustomobject]$checks
}

function New-HardwareSnapshot {
    param(
        [object]$Hardware,
        [object]$Plan,
        [string]$ProfileMode
    )

    return [ordered]@{
        profile_mode = $ProfileMode
        cpu_name = $Hardware.CpuName
        logical_cores = $Hardware.LogicalCores
        intel_gpu = $Hardware.PrimaryIntelGpu
        nvidia_gpu = $Hardware.PrimaryNvidiaGpu
        amd_gpu = $Hardware.PrimaryAmdGpu
        expected_hw_accel = if ($Plan) { $Plan.Choice.HardwareAccelerationType } else { 'none' }
        selected_vendor = if ($Plan) { $Plan.Choice.SelectedVendor } else { 'software' }
        qsv_encoders = if ($Plan -and $Plan.EncoderCaps) { @($Plan.EncoderCaps.Qsv) } else { @() }
        nvenc_encoders = if ($Plan -and $Plan.EncoderCaps) { @($Plan.EncoderCaps.Nvenc) } else { @() }
        amf_encoders = if ($Plan -and $Plan.EncoderCaps) { @($Plan.EncoderCaps.Amf) } else { @() }
    }
}
