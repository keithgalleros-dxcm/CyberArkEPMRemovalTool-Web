#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$LocalAddress = '192.168.1.100',
    [string]$RemoteSubnet = '192.168.1.0/24',
    [string]$PythonPath = 'C:\Python315\python.exe'
)
$ErrorActionPreference = 'Stop'
$assignedAddress = Get-NetIPAddress -IPAddress $LocalAddress -AddressFamily IPv4 -ErrorAction Stop
if ($assignedAddress.PrefixLength -ne 24 -or $RemoteSubnet -ne (($LocalAddress -replace '\.\d+$','.0') + '/24')) {
    throw 'This helper requires a matching /24 local subnet. Review other network layouts manually.'
}
if (!(Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Python executable not found.' }
$ruleName = 'Dexcom-EPM-Console-LAN-8765'
$existingRule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($existingRule) { Write-Output 'Named firewall rule already exists. Review its scope before changing it.'; exit 0 }
New-NetFirewallRule -Name $ruleName -DisplayName 'Dexcom EPM Console - trusted LAN TCP 8765' -Direction Inbound -Action Allow -Enabled True -Protocol TCP -LocalPort 8765 -LocalAddress $LocalAddress -RemoteAddress $RemoteSubnet -Program $PythonPath -Profile Any | Out-Null
Write-Output 'Added inbound TCP 8765 for the specified local IPv4, Python executable and /24 subnet.'

