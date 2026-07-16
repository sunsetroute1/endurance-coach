# Generate a strong API secret and append to .env if missing.
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot ".env"

if (-not (Test-Path $EnvFile)) {
    throw "Missing .env at $EnvFile"
}

$content = Get-Content $EnvFile -Raw
if ($content -match "(?m)^API_SECRET_KEY=(.*)$") {
    $current = $Matches[1].Trim()
    if ($current) {
        Write-Host "API_SECRET_KEY already set in .env"
        exit 0
    }
}

$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$key = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')

if ($content -match "(?m)^API_SECRET_KEY=") {
    $content = $content -replace "(?m)^API_SECRET_KEY=.*$", "API_SECRET_KEY=$key"
    Set-Content -Path $EnvFile -Value $content.TrimEnd() -Encoding utf8 -NoNewline
    Add-Content -Path $EnvFile -Value "" -Encoding utf8
} else {
    Add-Content -Path $EnvFile -Value "" -Encoding utf8
    Add-Content -Path $EnvFile -Value "# Bearer token for /api/v1/* and /mcp (required in production)" -Encoding utf8
    Add-Content -Path $EnvFile -Value "API_SECRET_KEY=$key" -Encoding utf8
}

Write-Host "Generated API_SECRET_KEY and saved to .env"
Write-Host "Read the value from .env and use: Authorization: Bearer <API_SECRET_KEY>"
