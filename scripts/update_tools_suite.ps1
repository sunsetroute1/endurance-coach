# Silent elevated updater for slskd, Navidrome, beets, Caddy, and Python deps.

param(

    [switch]$Elevated,

    [switch]$SkipServiceRestart,

    [string[]]$Tools = @()

)



$ErrorActionPreference = "Stop"



$ProjectRoot = Split-Path -Parent $PSScriptRoot

$LogDir = Join-Path $ProjectRoot "logs"

$LogFile = Join-Path $LogDir "update-tools.log"

$ReportFile = Join-Path $LogDir "update-tools-last.json"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null



. (Join-Path $PSScriptRoot "update_tool_helpers.ps1")

. (Join-Path $PSScriptRoot "scheduled_task_helpers.ps1")

$dockerHelpers = 'C:\ProgramData\docker\media-stack\scripts\docker-stack-helpers.ps1'
$dockerManagedArr = $false
$dockerManagedMusic = $false
if (Test-Path $dockerHelpers) {
    . $dockerHelpers
    $dockerManagedArr = (Get-DockerMediaStackProfile) -ne 'native'
    $dockerManagedMusic = Test-Path 'C:\ProgramData\docker\media-stack\music-active.marker'
}

    param([string]$Name)

    if ($Tools.Count -eq 0) { return $true }

    return $Name -in $Tools

}



if (-not $Elevated) {

    $forwardArgs = @()

    if ($SkipServiceRestart) { $forwardArgs += "-SkipServiceRestart" }

    foreach ($tool in $Tools) {

        $forwardArgs += "-Tools"

        $forwardArgs += $tool

    }

    Invoke-ElevatedUpdate -ScriptPath $PSCommandPath -ScriptArgs $forwardArgs

}



$results = [System.Collections.Generic.List[object]]::new()



function Add-Result {

    param(

        [string]$Tool,

        [string]$Status,

        [string]$Message,

        [string]$Before = "",

        [string]$After = ""

    )

    $entry = [pscustomobject]@{

        tool = $Tool

        status = $Status

        message = $Message

        before = $Before

        after = $After

    }

    $results.Add($entry) | Out-Null

    Write-UpdateLog -LogFile $LogFile -Message ("{0}: {1} ({2})" -f $Tool, $Status, $Message)

}



$scope = if ($Tools.Count -gt 0) { $Tools -join ", " } else { "all" }

Write-UpdateLog -LogFile $LogFile -Message "Update suite started (elevated=$($Elevated.IsPresent), scope=$scope)"



if (Test-ShouldUpdateTool "slskd") {

    try {

        $slskdDir = "C:\slskd"

        $slskdExe = Join-Path $slskdDir "slskd.exe"

        if (Test-Path $slskdExe) {

            $before = Get-ExeProductVersion $slskdExe

            $release = Get-GithubRelease -Repo "slskd/slskd"

            $asset = Get-ReleaseAssetUrl -Release $release -Pattern "^slskd-.*-win-x64\.zip$"

            $targetVersion = $release.tag_name

            if (Test-VersionAtLeastTag -Installed $before -Tag $targetVersion) {

                Add-Result -Tool "slskd" -Status "skipped" -Message "Already at $targetVersion" -Before $before -After $before

            } elseif ($asset) {

                Stop-ProcessByPidFile -PidFile (Join-Path $LogDir "slskd.pid") -ProcessName "slskd" -Ports @(5030)

                Start-Sleep -Seconds 3

                Install-GithubZipRelease -DownloadUrl $asset.Url -InstallDir $slskdDir

                $after = Get-ExeProductVersion $slskdExe

                Add-Result -Tool "slskd" -Status "updated" -Message "Installed $($asset.Name)" -Before $before -After $after

            } else {

                Add-Result -Tool "slskd" -Status "failed" -Message "Windows x64 asset not found for $targetVersion" -Before $before

            }

        } else {

            Add-Result -Tool "slskd" -Status "skipped" -Message "Not installed at $slskdExe"

        }

    } catch {

        Add-Result -Tool "slskd" -Status "failed" -Message $_.Exception.Message

    }

}



if (Test-ShouldUpdateTool "navidrome") {

    try {

        $navDir = "C:\Navidrome"

        $navExe = Join-Path $navDir "navidrome.exe"

        if (Test-Path $navExe) {

            $before = (& $navExe --version 2>&1 | Out-String).Trim()

            $release = Get-GithubRelease -Repo "navidrome/navidrome"

            $asset = Get-ReleaseAssetUrl -Release $release -Pattern "^navidrome_.*_windows_amd64\.zip$"

            $targetVersion = $release.tag_name.TrimStart("v")

            if (Test-VersionAtLeastTag -Installed $before -Tag $targetVersion) {

                Add-Result -Tool "navidrome" -Status "skipped" -Message "Already at $targetVersion" -Before $before -After $before

            } elseif ($asset) {

                Get-Process -Name "navidrome" -ErrorAction SilentlyContinue | Stop-Process -Force

                $navService = Get-Service -Name "Navidrome" -ErrorAction SilentlyContinue

                if ($navService) {

                    Stop-Service -Name "Navidrome" -Force -ErrorAction SilentlyContinue

                }

                Start-Sleep -Seconds 2

                Install-GithubZipRelease -DownloadUrl $asset.Url -InstallDir $navDir

                $after = (& $navExe --version 2>&1 | Out-String).Trim()

                if ($navService) {

                    Start-Service -Name "Navidrome" -ErrorAction SilentlyContinue

                } else {

                    $navStdout = Join-Path $LogDir "navidrome.stdout.log"

                    $navStderr = Join-Path $LogDir "navidrome.stderr.log"

                    Start-Process -FilePath $navExe -WorkingDirectory $navDir -WindowStyle Hidden `

                        -RedirectStandardOutput $navStdout -RedirectStandardError $navStderr | Out-Null

                }

                Add-Result -Tool "navidrome" -Status "updated" -Message "Installed $($asset.Name)" -Before $before -After $after

            } else {

                Add-Result -Tool "navidrome" -Status "failed" -Message "Windows amd64 asset not found" -Before $before

            }

        } else {

            Add-Result -Tool "navidrome" -Status "skipped" -Message "Not installed at $navExe"

        }

    } catch {

        Add-Result -Tool "navidrome" -Status "failed" -Message $_.Exception.Message

    }

}



if (Test-ShouldUpdateTool "caddy") {

    try {

        $caddyExe = "C:\Caddy\caddy.exe"

        if (Test-Path $caddyExe) {

            $before = (& $caddyExe version 2>&1 | Out-String).Trim()

            if (Get-Command winget -ErrorAction SilentlyContinue) {

                winget upgrade --id Caddy.Caddy -e --accept-source-agreements --accept-package-agreements --silent | Out-Null

                $after = (& $caddyExe version 2>&1 | Out-String).Trim()

                if ($after -eq $before) {

                    Add-Result -Tool "caddy" -Status "skipped" -Message "Already current via winget" -Before $before -After $after

                } else {

                    Add-Result -Tool "caddy" -Status "updated" -Message "Upgraded via winget" -Before $before -After $after

                }

            } else {

                Add-Result -Tool "caddy" -Status "skipped" -Message "winget unavailable; skipped" -Before $before

            }

        } else {

            Add-Result -Tool "caddy" -Status "skipped" -Message "Not installed at $caddyExe"

        }

    } catch {

        Add-Result -Tool "caddy" -Status "failed" -Message $_.Exception.Message

    }

}



if (Test-ShouldUpdateTool "beets") {

    try {

        $musicPython = Join-Path $ProjectRoot "services\music-ingest\.venv\Scripts\python.exe"

        $musicReq = Join-Path $ProjectRoot "services\music-ingest\requirements.txt"

        $before = Get-PipPackageVersion -PythonExe $musicPython -PackageName "beets"

        Update-PipRequirements -PythonExe $musicPython -RequirementsFile $musicReq -Label "beets"

        $after = Get-PipPackageVersion -PythonExe $musicPython -PackageName "beets"

        if ($after -eq $before) {

            Add-Result -Tool "beets" -Status "skipped" -Message "Already at $after" -Before $before -After $after

        } else {

            Add-Result -Tool "beets" -Status "updated" -Message "pip upgrade complete" -Before $before -After $after

        }

    } catch {

        Add-Result -Tool "beets" -Status "failed" -Message $_.Exception.Message

    }

}



if (Test-ShouldUpdateTool "endurance-coach") {

    try {

        $appPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

        $appReq = Join-Path $ProjectRoot "requirements.txt"

        $before = Get-PipPackageVersion -PythonExe $appPython -PackageName "garminconnect"

        Update-PipRequirements -PythonExe $appPython -RequirementsFile $appReq -Label "endurance-coach"

        & $appPython -m pip install -U -e $ProjectRoot | Out-Null

        $after = Get-PipPackageVersion -PythonExe $appPython -PackageName "garminconnect"

        if ($after -eq $before) {

            Add-Result -Tool "endurance-coach" -Status "skipped" -Message "Already at $after" -Before $before -After $after

        } else {

            Add-Result -Tool "endurance-coach" -Status "updated" -Message "pip upgrade complete" -Before $before -After $after

        }

    } catch {

        Add-Result -Tool "endurance-coach" -Status "failed" -Message $_.Exception.Message

    }

}



$wingetApps = @(

    @{ Tool = "jellyfin"; Id = "Jellyfin.Jellyfin"; Service = "JellyfinServer" },

    @{ Tool = "radarr"; Id = "Radarr.Radarr"; Service = "Radarr" },

    @{ Tool = "sonarr"; Id = "Sonarr.Sonarr"; Service = "Sonarr" },

    @{ Tool = "prowlarr"; Id = "Prowlarr.Prowlarr"; Service = "Prowlarr" },

    @{ Tool = "bazarr"; Id = "Bazarr.Bazarr"; Service = "Bazarr" }

)



foreach ($app in $wingetApps) {

    if (-not (Test-ShouldUpdateTool $app.Tool)) { continue }

    if ($dockerManagedArr -and $app.Tool -in @('radarr', 'sonarr', 'prowlarr', 'bazarr')) {
        Add-Result -Tool $app.Tool -Status "skipped" -Message "Managed by Docker media stack"
        continue
    }

    try {

        $service = Get-Service -Name $app.Service -ErrorAction SilentlyContinue

        if (-not $service -and -not (Get-Command winget -ErrorAction SilentlyContinue)) {

            Add-Result -Tool $app.Tool -Status "skipped" -Message "Not installed"

            continue

        }

        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {

            Add-Result -Tool $app.Tool -Status "skipped" -Message "winget unavailable"

            continue

        }

        $before = (winget list --id $app.Id -e 2>$null | Out-String).Trim()

        winget upgrade --id $app.Id -e --accept-source-agreements --accept-package-agreements --silent | Out-Null

        $after = (winget list --id $app.Id -e 2>$null | Out-String).Trim()

        if ($after -eq $before) {

            Add-Result -Tool $app.Tool -Status "skipped" -Message "Already current via winget" -Before $before -After $after

        } else {

            if ($service) {

                Restart-Service -Name $app.Service -Force -ErrorAction SilentlyContinue

            }

            Add-Result -Tool $app.Tool -Status "updated" -Message "Upgraded via winget" -Before $before -After $after

        }

    } catch {

        Add-Result -Tool $app.Tool -Status "failed" -Message $_.Exception.Message

    }

}



if (-not $SkipServiceRestart) {

    $updatedTools = @($results | Where-Object { $_.status -eq "updated" } | ForEach-Object { $_.tool })

    if ($updatedTools.Count -gt 0) {

        Write-UpdateLog -LogFile $LogFile -Message ("Restarting services for updated tools: {0}" -f ($updatedTools -join ", "))

    } else {

        Write-UpdateLog -LogFile $LogFile -Message "No tool binaries changed; skipping service restarts"

    }



    if ($updatedTools -contains "slskd" -or $updatedTools -contains "navidrome" -or $updatedTools -contains "beets") {

        if ($updatedTools -contains "slskd") {
            if ($dockerManagedMusic -and (Get-Command Invoke-DockerMediaStackRecovery -ErrorAction SilentlyContinue)) {
                Invoke-DockerMediaStackRecovery -Reason 'tool-update-slskd' -StartupWaitSec 30 | Out-Null
            } else {
                & (Join-Path $PSScriptRoot "start_slskd_windows.ps1") | Out-Null
            }
            if (-not (Wait-PortOpen -Port 5030 -TimeoutSeconds 45)) {
                Write-UpdateLog -LogFile $LogFile -Message "WARNING: slskd did not open port 5030 after restart"
            }
        }

        & (Join-Path $ProjectRoot "scripts\music-ingest\fix_music_ingest.ps1") | Out-Null

    }



    if ($updatedTools -contains "endurance-coach") {
        $coachHelpers = Join-Path $PSScriptRoot "coach-stack-helpers.ps1"
        if (Test-Path $coachHelpers) {
            . $coachHelpers
            if (Test-CoachDockerMode) {
                Invoke-CoachDockerRecovery -Reason 'tool-update-endurance-coach' -StartupWaitSec 40 | Out-Null
            } else {
                Invoke-SilentPowerShell -ScriptPath (Join-Path $ProjectRoot "scripts\restart_app_services.ps1") -Wait | Out-Null
            }
        } else {
            Invoke-SilentPowerShell -ScriptPath (Join-Path $ProjectRoot "scripts\restart_app_services.ps1") -Wait | Out-Null
        }

    }



    if ($updatedTools -contains "caddy") {

        & (Join-Path $ProjectRoot "scripts\reload_caddy.ps1") | Out-Null

    }

}



$report = [pscustomobject]@{

    updated_at = (Get-Date).ToUniversalTime().ToString("o")

    scope = $scope

    results = $results

}

$report | ConvertTo-Json -Depth 4 | Out-File -FilePath $ReportFile -Encoding utf8



$failures = @($results | Where-Object { $_.status -eq "failed" })

Write-UpdateLog -LogFile $LogFile -Message ("Update suite finished: {0} updated/skipped, {1} failed" -f `

    ($results.Count - $failures.Count), $failures.Count)



if ($failures.Count -gt 0) {

    exit 1

}

exit 0

