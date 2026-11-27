$ErrorActionPreference = 'Continue'
"== ComputerName: $env:COMPUTERNAME"
$cs = Get-CimInstance Win32_ComputerSystem
"== Domain: $($cs.Domain)  PartOfDomain: $($cs.PartOfDomain)"
"== OS: $((Get-CimInstance Win32_OperatingSystem).Caption)"
"== IPv4:"
Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '169.*' -and $_.IPAddress -ne '127.0.0.1'} | ForEach-Object {"  $($_.InterfaceAlias): $($_.IPAddress)"}
"== DNS Client:"
Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object {$_.ServerAddresses} | ForEach-Object {"  $($_.InterfaceAlias): $($_.ServerAddresses -join ',')"}
"== AD/DNS feature state:"
Get-WindowsFeature AD-Domain-Services,DNS | Format-Table Name,InstallState -AutoSize | Out-String
"== Disk C: free GB: $([math]::Round((Get-PSDrive C).Free/1GB,1))"
"== Services:"
Get-Service NTDS,Netlogon,kdc,DNS -ErrorAction SilentlyContinue | Format-Table Name,Status -AutoSize | Out-String
"== Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
