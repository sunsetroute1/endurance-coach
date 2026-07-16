# Create the native Windows music ingestion directory layout.
$ErrorActionPreference = "Stop"

$dirs = @(
    "E:\Music\Incoming\Soulseek",
    "E:\Music\Incoming\Soulseek\incomplete",
    "E:\Music\Library",
    "E:\Music\Quarantine",
    "E:\Music\State"
)

foreach ($dir in $dirs) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Write-Host "Ensured $dir"
}

Write-Host ""
Write-Host "Directory layout ready under E:\Music"
