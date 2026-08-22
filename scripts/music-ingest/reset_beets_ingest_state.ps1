# Reset beets ingest state so previously skipped Incoming folders are retried.
$ErrorActionPreference = "Stop"

$StateDir = "E:\Music\State"
$Processed = Join-Path $StateDir "processed-paths.json"
$Backup = Join-Path $StateDir ("processed-paths.backup-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")

if (Test-Path $Processed) {
    Copy-Item $Processed $Backup -Force
    Remove-Item $Processed -Force
    Write-Host "Reset $Processed (backup: $Backup)"
} else {
    Write-Host "No processed-paths.json to reset"
}

$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$BeetsTemplate = Join-Path $RepoRoot "services\music-ingest\config\beets-config.yaml"
$BeetsConfig = Join-Path $env:APPDATA "beets\config.yaml"
Copy-Item $BeetsTemplate $BeetsConfig -Force
Write-Host "Deployed beets config to $BeetsConfig"

Write-Host "Run: powershell -File `"$PSScriptRoot\run_beets_import.ps1`" -ScanOnce"
