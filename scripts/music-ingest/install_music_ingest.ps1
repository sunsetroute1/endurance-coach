# Install beets + watcher venv, configs, and scheduled tasks for music ingestion.
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$IngestRoot = Join-Path $RepoRoot "services\music-ingest"
$VenvDir = Join-Path $IngestRoot ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $IngestRoot "requirements.txt"
$BeetsTemplate = Join-Path $IngestRoot "config\beets-config.yaml"
$PipelineTemplate = Join-Path $IngestRoot "config\pipeline.env.example"
$PipelineEnv = Join-Path $IngestRoot "config\pipeline.env"
$BeetsConfigDir = Join-Path $env:APPDATA "beets"
$BeetsConfig = Join-Path $BeetsConfigDir "config.yaml"

. (Join-Path $RepoRoot "scripts\scheduled_task_helpers.ps1")

Write-Host "==> Creating media directories"
& (Join-Path $PSScriptRoot "setup_music_directories.ps1")

Write-Host "==> Creating Python venv at $VenvDir"
if (-not (Test-Path $PythonExe)) {
    python -m venv $VenvDir
}
& $PythonExe -m pip install --upgrade pip wheel | Out-Null
& $PythonExe -m pip install -r $Requirements

Write-Host "==> Installing beets config"
New-Item -ItemType Directory -Force -Path $BeetsConfigDir | Out-Null
Copy-Item -Path $BeetsTemplate -Destination $BeetsConfig -Force
$pluginPath = (Join-Path $IngestRoot "plugins") -replace '\\', '/'
$beetsContent = ((Get-Content $BeetsConfig -Raw) -replace 'MUSIC_INGEST_PLUGINPATH', $pluginPath).TrimEnd()
# Beets rewrite uses literal replacements; legacy rules with ": \1" corrupt titles to "\1".
$beetsContent = $beetsContent -replace '(?m)^  (?:artist|album|albumartist|title) \^\d+\\\.?\s+\(\.\+\)\$: \\1\r?\n', ''
[System.IO.File]::WriteAllText($BeetsConfig, $beetsContent + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

function Set-BeetsLastFmKey {
    param([string]$ConfigPath, [string]$ApiKey)
    if (-not $ApiKey) { return }
    $content = Get-Content $ConfigPath -Raw
    if ($content -match '(?m)^  lastfm_key:') {
        $content = $content -replace '(?m)^  lastfm_key:.*$', "  lastfm_key: $ApiKey"
    } else {
        $content = $content -replace '(?m)^fetchart:', "fetchart:`n  lastfm_key: $ApiKey"
    }
    if ($content -notmatch '(?m)^    - lastfm\s*$') {
        $content = $content -replace '(?m)^    - wikipedia\s*$', "    - wikipedia`n    - lastfm"
    }
    [System.IO.File]::WriteAllText($ConfigPath, $content.TrimEnd() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Configured Last.fm API key in beets fetchart config"
}

if (-not (Test-Path $PipelineEnv)) {
    Copy-Item -Path $PipelineTemplate -Destination $PipelineEnv -Force
    Write-Host "Created $PipelineEnv"
} else {
    $pipelineContent = Get-Content $PipelineEnv -Raw
    $pipelineContent = $pipelineContent -replace 'LIBRARY_DIR=E:\\Music\\Library', 'LIBRARY_DIR=E:\Music'
    [System.IO.File]::WriteAllText(
        $PipelineEnv,
        $pipelineContent.TrimEnd() + [Environment]::NewLine,
        [System.Text.UTF8Encoding]::new($false))
}

function Set-NavidromeLastFm {
    param(
        [string]$ConfigPath,
        [string]$ApiKey,
        [string]$ApiSecret
    )
    if (-not $ApiKey) { return }
    $content = Get-Content $ConfigPath -Raw
    if ($content -notmatch '\[LastFM\]') {
        $block = @"

[LastFM]
Enabled = true
ApiKey = "$ApiKey"
Secret = "$ApiSecret"
"@
        if ($content -match '(?m)^LyricsPriority = ') {
            $lyrics = "embedded,.lrc,nd-lyrics,navidrome-shazam-plugin"
            if ($content -match '(?m)^LyricsPriority = "([^"]+)"') {
                $lyrics = $Matches[1]
            }
            $content = $content -replace '(?m)^LyricsPriority = ".*"\r?$', "$block`nLyricsPriority = `"$lyrics`""
        } else {
            $content = $content.TrimEnd() + $block + [Environment]::NewLine
        }
    } else {
        if ($content -match '(?m)^ApiKey = ') {
            $content = $content -replace '(?m)^ApiKey = ".*"$', "ApiKey = `"$ApiKey`""
        } else {
            $content = $content -replace '(?m)^\[LastFM\]', "[LastFM]`nApiKey = `"$ApiKey`""
        }
        if ($ApiSecret) {
            if ($content -match '(?m)^Secret = ') {
                $content = $content -replace '(?m)^Secret = ".*"$', "Secret = `"$ApiSecret`""
            } else {
                $content = $content -replace '(?m)^ApiKey = ".*"$', "ApiKey = `"$ApiKey`"`nSecret = `"$ApiSecret`""
            }
        }
        if ($content -match '(?m)^Enabled = ') {
            $content = $content -replace '(?m)^Enabled = .*$', "Enabled = true"
        }
    }
    [System.IO.File]::WriteAllText($ConfigPath, $content.TrimEnd() + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Configured Last.fm credentials in Navidrome config"
}

$lastFmKey = ""
$lastFmSecret = ""
if (Test-Path $PipelineEnv) {
    foreach ($line in Get-Content $PipelineEnv) {
        if ($line -match '^\s*LASTFM_API_KEY=(.+)$') {
            $lastFmKey = $Matches[1].Trim().Trim('"')
        }
        if ($line -match '^\s*LASTFM_API_SECRET=(.+)$') {
            $lastFmSecret = $Matches[1].Trim().Trim('"')
        }
    }
}
Set-BeetsLastFmKey -ConfigPath $BeetsConfig -ApiKey $lastFmKey

Write-Host "==> Updating slskd paths"
$SlskdConfig = "C:\slskd\data\slskd.yml"
if (Test-Path $SlskdConfig) {
    $content = Get-Content $SlskdConfig -Raw
    $content = $content -replace "incomplete: E:\\Music\\incomplete", "incomplete: E:\Music\Incoming\Soulseek\incomplete"
    $content = $content -replace "downloads: E:\\Music", "downloads: E:\Music\Incoming\Soulseek"
    $content = $content -replace "- E:\\Music\\Library", "- E:\Music"
    Set-Content -Path $SlskdConfig -Value $content.TrimEnd() -Encoding utf8
    Write-Host "Updated $SlskdConfig"
}

Write-Host "==> Updating Navidrome config"
$NavidromeTemplate = Join-Path $IngestRoot "config\navidrome.toml"
$DockerMarker = "C:\ProgramData\docker\media-stack\music-active.marker"
$DockerNavidromeConfig = "C:\ProgramData\docker\media-stack\config\navidrome\navidrome.toml"
$NavidromeConfig = if ((Test-Path $DockerMarker) -and (Test-Path $DockerNavidromeConfig)) {
    $DockerNavidromeConfig
} else {
    "C:\Navidrome\navidrome.toml"
}

function Update-NavidromeConfigContent([string]$Content, [string]$TemplatePath) {
    $content = $Content -replace 'MusicFolder = "E:\\Music\\Library"', 'MusicFolder = "E:\\Music"'
    # Navidrome 0.63+ uses [Scanner].Schedule; top-level ScanSchedule is ignored.
    $content = $content -replace '(?m)^ScanSchedule\s*=.*\r?\n', ''
    if ($content -match '(?m)^\[Scanner\]' -and $content -notmatch '(?m)^\s*Schedule\s*=') {
        $content = $content -replace '(?m)^(\[Scanner\]\s*\r?\n)', "`$1Schedule = `"@every 5m`"`n"
    } elseif ($content -notmatch '(?m)^\[Scanner\]') {
        $content = $content.TrimEnd() + "`n`n[Scanner]`nSchedule = `"@every 5m`"`nPurgeMissing = `"full`"`n"
    }
    if (Test-Path $TemplatePath) {
        $template = Get-Content $TemplatePath -Raw
        if ($template -match '(?m)^Agents = "([^"]+)"') {
            $agents = $Matches[1]
            if ($content -match '(?m)^Agents = ') {
                $content = $content -replace '(?m)^Agents = ".*"\r?$', "Agents = `"$agents`""
            } else {
                $content = $content.TrimEnd() + "`nAgents = `"$agents`"`n"
            }
        }
        if ($template -match '(?m)^LyricsPriority = "([^"]+)"') {
            $lyrics = $Matches[1]
            if ($content -match '(?m)^LyricsPriority = ') {
                $content = $content -replace '(?m)^LyricsPriority = ".*"$', "LyricsPriority = `"$lyrics`""
            }
        }
    }
    if ($content -notmatch '\[Tags\.releasedate\]') {
        $m4aTagBlock = @"

# iTunes / m4a tagging: ignore the @day atom for release date so AAC albums
# imported from macOS do not split away from MP3/FLAC copies of the same album.
[Tags.releasedate]
Aliases = ["tdrl", "releasedate"]
"@
        $content = $content.TrimEnd() + $m4aTagBlock + [Environment]::NewLine
    }
    return $content.TrimEnd() + [Environment]::NewLine
}

if (Test-Path $NavidromeTemplate) {
    if (-not (Test-Path $NavidromeConfig)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $NavidromeConfig -Parent) | Out-Null
        Copy-Item -Path $NavidromeTemplate -Destination $NavidromeConfig -Force
        if ($NavidromeConfig -eq $DockerNavidromeConfig) {
            python (Join-Path "C:\ProgramData\docker\media-stack\scripts" "migrate-navidrome-config.py") $NavidromeConfig
        }
        Write-Host "Installed $NavidromeConfig from template"
        Set-NavidromeLastFm -ConfigPath $NavidromeConfig -ApiKey $lastFmKey -ApiSecret $lastFmSecret
    } else {
        $content = Update-NavidromeConfigContent (Get-Content $NavidromeConfig -Raw) $NavidromeTemplate
        [System.IO.File]::WriteAllText($NavidromeConfig, $content, [System.Text.UTF8Encoding]::new($false))
        Write-Host "Updated $NavidromeConfig (restart Navidrome to apply)"
    }
    Set-NavidromeLastFm -ConfigPath $NavidromeConfig -ApiKey $lastFmKey -ApiSecret $lastFmSecret
} elseif (Test-Path $NavidromeConfig) {
    $content = Update-NavidromeConfigContent (Get-Content $NavidromeConfig -Raw) $NavidromeTemplate
    [System.IO.File]::WriteAllText($NavidromeConfig, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Updated $NavidromeConfig (restart Navidrome to apply)"
    Set-NavidromeLastFm -ConfigPath $NavidromeConfig -ApiKey $lastFmKey -ApiSecret $lastFmSecret
}

Write-Host "==> Installing Navidrome metadata plugins"
& (Join-Path $PSScriptRoot "install_navidrome_metadata_plugins.ps1")

Write-Host "==> Registering scheduled tasks"
& (Join-Path $PSScriptRoot "install_music_watcher_startup.ps1")
& (Join-Path $PSScriptRoot "install_music_ingest_fallback.ps1")

Write-Host ""
Write-Host "Music ingestion pipeline installed."
Write-Host "  Incoming : E:\Music\Incoming\Soulseek"
Write-Host "  Output   : E:\Music"
Write-Host "  Beets cfg: $BeetsConfig"
Write-Host "  Logs     : $(Join-Path $RepoRoot 'logs\music-ingest.log')"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Restart slskd and Navidrome (enable plugins in Navidrome Settings)"
Write-Host "  2. Optional: add LASTFM_API_KEY to services\music-ingest\config\pipeline.env, rerun this installer"
Write-Host "  3. Backfill art/genres: powershell -File `"$(Join-Path $PSScriptRoot 'enrich_library_metadata.ps1')`" -RescanNavidrome"
Write-Host "  4. Test import: powershell -File `"$(Join-Path $PSScriptRoot 'run_beets_import.ps1')`" -ScanOnce"
Write-Host "  5. See docs\MUSIC_INGEST_PIPELINE.md"
