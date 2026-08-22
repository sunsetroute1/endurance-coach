# Configure Windows auto-login for the media server user session.
# Required so Interactive scheduled tasks (Docker, Watchboard, media stack) run after power-loss reboots.
param(
    [string]$Username = $env:USERNAME,
    [SecureString]$Password,
    [switch]$Disable
)

$ErrorActionPreference = 'Stop'

function Test-IsAdministrator {
    return ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )
}

function Convert-SecureStringToPlainText {
    param([Parameter(Mandatory = $true)][SecureString]$Secure)
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

if (-not (Test-IsAdministrator)) {
    throw 'Run elevated: auto-login changes require administrator privileges.'
}

$winlogonKey = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'

if ($Disable) {
    Remove-ItemProperty -Path $winlogonKey -Name 'AutoAdminLogon' -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $winlogonKey -Name 'DefaultPassword' -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $winlogonKey -Name 'ForceAutoLogon' -ErrorAction SilentlyContinue
    Set-ItemProperty -Path $winlogonKey -Name 'AutoAdminLogon' -Value '0' -Type String
    Write-Host 'Auto-login disabled.'
    exit 0
}

if (-not $Password) {
    try {
        Add-Type -AssemblyName System.Security -ErrorAction Stop
        $cred = Get-Credential -UserName "$env:COMPUTERNAME\$Username" `
            -Message "Enter Windows password for auto-login (stored in Winlogon registry)"
        if ($cred) {
            $Password = $cred.Password
        }
    } catch {
        $Password = Read-Host "Enter Windows password for '$Username' (stored in Winlogon registry for auto-login)" -AsSecureString
    }
}
if (-not $Password -or $Password.Length -eq 0) {
    throw 'Password is required for auto-login.'
}

$plainPassword = Convert-SecureStringToPlainText -Secure $Password
$computerName = $env:COMPUTERNAME

# Win11 may block auto-login when "Windows Hello / passwordless sign-in" is enabled.
$passwordlessKey = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device'
if (-not (Test-Path $passwordlessKey)) {
    New-Item -Path $passwordlessKey -Force | Out-Null
}
Set-ItemProperty -Path $passwordlessKey -Name 'DevicePasswordLessBuildVersion' -Value 0 -Type DWord

Set-ItemProperty -Path $winlogonKey -Name 'AutoAdminLogon' -Value '1' -Type String
Set-ItemProperty -Path $winlogonKey -Name 'DefaultUserName' -Value $Username -Type String
Set-ItemProperty -Path $winlogonKey -Name 'DefaultPassword' -Value $plainPassword -Type String
Set-ItemProperty -Path $winlogonKey -Name 'DefaultDomainName' -Value $computerName -Type String
Set-ItemProperty -Path $winlogonKey -Name 'ForceAutoLogon' -Value '1' -Type String

Write-Host "Auto-login enabled for '$Username' on $computerName."
Write-Host 'After the next reboot, Windows will sign in automatically and start logon/boot scheduled tasks.'
Write-Host ''
Write-Host 'Security note: the password is stored in the Winlogon registry (standard Windows auto-login behavior).'
Write-Host 'Disable later with: .\configure_media_server_autologin.ps1 -Disable'
