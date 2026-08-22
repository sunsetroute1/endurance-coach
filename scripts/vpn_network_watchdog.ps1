param(
    [switch]$ForceRecovery
)

# Lightweight entry point for scheduled watchdogs to detect VPN/network transitions.
$ErrorActionPreference = 'Continue'

. (Join-Path $PSScriptRoot 'network_vpn_helpers.ps1')

$result = Invoke-VpnNetworkWatchdog -ForceRecovery:$ForceRecovery
if ($result.recovered) {
    $reason = if ($result.reason) { $result.reason } else { 'network-change' }
    Write-Host "VPN/network recovery completed ($reason): $($result.current.signature)"
    exit 0
}
if ($result.changed) {
    Write-Host "VPN/network change detected but recovery skipped: $($result.current.signature)"
}
exit 0
