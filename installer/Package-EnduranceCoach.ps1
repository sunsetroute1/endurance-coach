#Requires -Version 5.1
<#
.SYNOPSIS
  Package the endurance-coach installer tree for distribution.

.DESCRIPTION
  Validates key install files, writes installer/package-manifest.json, and
  optionally creates dist/endurance-coach-installer-YYYYMMDD.zip.

.PARAMETER ProjectRoot
  Repo root. Defaults to parent of installer/.

.PARAMETER SkipZip
  Write manifest only; do not create a zip archive.
#>
param(
    [string]$ProjectRoot = "",
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$InstallerDir = Join-Path $ProjectRoot "installer"
$DistDir = Join-Path $ProjectRoot "dist"
$ManifestPath = Join-Path $InstallerDir "package-manifest.json"
$Stamp = Get-Date -Format "yyyyMMdd"
$ZipPath = Join-Path $DistDir "endurance-coach-installer-$Stamp.zip"

$requiredRelPaths = @(
    "installer\Install-EnduranceCoach.ps1",
    "installer\Package-EnduranceCoach.ps1",
    "docker-compose.yml",
    "scripts\garmin_auth.py",
    "scripts\coach-stack-helpers.ps1",
    "scripts\install_all_services.ps1",
    "scripts\generate_api_secret.ps1",
    "src\endurance_coach\mcp\http_middleware.py",
    "src\endurance_coach\mcp\server.py",
    ".env.example",
    "requirements.txt"
)

Write-Host "Packaging endurance-coach installer"
Write-Host "Project root: $ProjectRoot"
Write-Host ""

$checklist = @()
$missing = @()
foreach ($rel in $requiredRelPaths) {
    $full = Join-Path $ProjectRoot $rel
    $ok = Test-Path $full
    $checklist += [ordered]@{
        path   = $rel.Replace("\", "/")
        exists = $ok
    }
    if ($ok) {
        Write-Host "  OK  $rel" -ForegroundColor Green
    } else {
        Write-Host "  MISSING  $rel" -ForegroundColor Red
        $missing += $rel
    }
}

if ($missing.Count -gt 0) {
    throw "Package validation failed; missing $($missing.Count) required file(s)."
}

$manifest = [ordered]@{
    name             = "endurance-coach-installer"
    created_at       = (Get-Date).ToString("o")
    # Relative to repo root — never embed absolute machine paths.
    project_root     = "."
    stamp            = $Stamp
    checklist        = $checklist
    install_commands = @(
        "powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1 -Docker",
        "powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1 -Repair",
        "powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1 -Repair -Docker"
    )
}

$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $ManifestPath -Encoding utf8
Write-Host ""
Write-Host "Wrote manifest: $ManifestPath" -ForegroundColor Cyan

if (-not $SkipZip) {
    New-Item -ItemType Directory -Force -Path $DistDir | Out-Null
    if (Test-Path $ZipPath) {
        Remove-Item $ZipPath -Force
    }

    # Keep the zip lean: source + installer + scripts — not local data dumps or builds.
    $excludeDirNames = @(
        ".venv", "__pycache__", ".git", "logs", "dist", "data", "android", "config",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules", "docker-data"
    )
    $excludeFiles = @(
        "*.pyc", ".env", "coach-active.marker", "resource-limits.env", "energy-report.html",
        "local.json", "GARMIN_ACTIVITY_DETAILS.md", "GARMIN_METRICS.md",
        "GARMIN_RECOVERY.md", "GARMIN_TRENDS.md"
    )
    $staging = Join-Path $env:TEMP "endurance-coach-pkg-$Stamp-$PID"
    if (Test-Path $staging) {
        Remove-Item $staging -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $staging | Out-Null

    Write-Host "Staging files for zip (excluding data/, android/, .venv, logs, secrets)..."
    $robocopyArgs = @(
        $ProjectRoot, $staging, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP",
        "/XD"
    ) + $excludeDirNames + @("/XF") + $excludeFiles
    & robocopy @robocopyArgs | Out-Null
    # robocopy exit codes 0-7 are success
    if ($LASTEXITCODE -ge 8) {
        Write-Warning "robocopy reported exit $($LASTEXITCODE); falling back to Copy-Item"
        Get-ChildItem $ProjectRoot -Force | ForEach-Object {
            if ($excludeDirNames -contains $_.Name) { return }
            if ($excludeFiles -contains $_.Name) { return }
            Copy-Item $_.FullName -Destination (Join-Path $staging $_.Name) -Recurse -Force
        }
    }

    Get-ChildItem -Path $staging -Recurse -Filter "*.pyc" -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    $envStaged = Join-Path $staging ".env"
    if (Test-Path $envStaged) {
        Remove-Item $envStaged -Force -ErrorAction SilentlyContinue
    }

    try {
        # Prefer tar when available (handles long paths better than Compress-Archive).
        $tar = Get-Command tar -ErrorAction SilentlyContinue
        if ($tar) {
            Push-Location $staging
            try {
                & tar -a -cf $ZipPath *
                if ($LASTEXITCODE -ne 0) { throw "tar exit $LASTEXITCODE" }
            } finally {
                Pop-Location
            }
        } else {
            Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $ZipPath -Force
        }
        Write-Host "Created zip: $ZipPath" -ForegroundColor Cyan
    } catch {
        Write-Warning "Archive failed: $($_.Exception.Message)"
        Write-Host "Manifest was still written; zip step skipped."
    } finally {
        Remove-Item $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1 -Docker"
Write-Host "  powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1 -Repair"
Write-Host "  powershell -ExecutionPolicy Bypass -File installer\Install-EnduranceCoach.ps1 -Repair -Docker"
Write-Host ""
Write-Host "Package complete."
