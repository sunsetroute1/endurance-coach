# Print the streamable-http MCP connector JSON for Cursor / Perplexity.
param(
    [switch]$PublicUrl
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $ProjectRoot ".env"

function Get-EnvValue([string]$Name) {
    if (-not (Test-Path $EnvFile)) { return $null }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^\s*$Name=(.*)$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

$token = Get-EnvValue "API_SECRET_KEY"
$publicBase = Get-EnvValue "PUBLIC_BASE_URL"
if (-not $token) {
    Write-Error "API_SECRET_KEY is missing from .env"
}

$url = if ($PublicUrl -and $publicBase -match "^https?://") {
    ($publicBase.TrimEnd("/") + "/mcp")
} else {
    "http://127.0.0.1:8080/mcp"
}

$config = @{
    url = $url
    transport = "streamable-http"
    headers = @{
        Authorization = "Bearer $token"
        Accept = "application/json"
    }
} | ConvertTo-Json -Depth 4

Write-Host "MCP connector config:"
Write-Host $config
Write-Host ""
Write-Host "Server mode: MCP_STATELESS_HTTP=true (no sticky session required)."
Write-Host "Quick check: .venv\Scripts\python.exe scripts\verify_mcp_tools.py"
Write-Host "No-session call check: .venv\Scripts\python.exe scripts\mcp_perplexity_invoke_check.py"
