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

if (-not (Test-Path $PipelineEnv)) {
    Copy-Item -Path $PipelineTemplate -Destination $PipelineEnv -Force
    Write-Host "Created $PipelineEnv"
}

Write-Host "==> Updating slskd paths"
$SlskdConfig = "C:\slskd\data\slskd.yml"
if (Test-Path $SlskdConfig) {
    $content = Get-Content $SlskdConfig -Raw
    $content = $content -replace "incomplete: E:\\Music\\incomplete", "incomplete: E:\Music\Incoming\Soulseek\incomplete"
    $content = $content -replace "downloads: E:\\Music", "downloads: E:\Music\Incoming\Soulseek"
    $content = $content -replace "- E:\\Music", "- E:\Music\Library"
    Set-Content -Path $SlskdConfig -Value $content.TrimEnd() -Encoding utf8
    Write-Host "Updated $SlskdConfig"
}

Write-Host "==> Updating Navidrome music folder"
$NavidromeConfig = "C:\Navidrome\navidrome.toml"
if (Test-Path $NavidromeConfig) {
    $content = Get-Content $NavidromeConfig -Raw
    $content = $content -replace 'MusicFolder = "E:\\\\Music"', 'MusicFolder = "E:\\Music\\Library"'
    Set-Content -Path $NavidromeConfig -Value $content.TrimEnd() -Encoding utf8
    Write-Host "Updated $NavidromeConfig (restart Navidrome to apply)"
}

Write-Host "==> Registering scheduled tasks"
& (Join-Path $PSScriptRoot "install_music_watcher_startup.ps1")
& (Join-Path $PSScriptRoot "install_music_ingest_fallback.ps1")

Write-Host ""
Write-Host "Music ingestion pipeline installed."
Write-Host "  Incoming : E:\Music\Incoming\Soulseek"
Write-Host "  Library  : E:\Music\Library"
Write-Host "  Beets cfg: $BeetsConfig"
Write-Host "  Logs     : $(Join-Path $RepoRoot 'logs\music-ingest.log')"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Restart slskd and Navidrome"
Write-Host "  2. Test: powershell -File `"$(Join-Path $PSScriptRoot 'run_beets_import.ps1')`" -ScanOnce"
Write-Host "  3. See docs\MUSIC_INGEST_PIPELINE.md"
