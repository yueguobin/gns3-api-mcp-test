$ErrorActionPreference = 'Continue'
"== LocalMachine\My certificates:"
Get-ChildItem Cert:\LocalMachine\My | ForEach-Object {
  $eku = ($_.Extensions | Where-Object {$_.Oid.FriendlyName -match 'Enhanced Key Usage'}).EnhancedKeyUsages | ForEach-Object FriendlyName
  $san = ($_.Extensions | Where-Object {$_.Oid.FriendlyName -match 'Subject Alternative Name'}).Format($false)
  [pscustomobject]@{
    Subject = $_.Subject; Thumb = $_.Thumbprint.Substring(0,12); NotAfter = $_.NotAfter
    HasKey = $_.HasPrivateKey; EKU = ($eku -join ','); SAN = $san; Friendly = $_.FriendlyName
  }
} | Format-List | Out-String

"== Schannel events (System log, last 12):"
Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Schannel'} -MaxEvents 12 -ErrorAction SilentlyContinue |
  ForEach-Object { "[$($_.Id)] $($_.TimeCreated) $($_.Message)" } | Out-String

"== LSASS/LDAP-related events (last 10):"
Get-WinEvent -LogName 'Directory Service' -MaxEvents 10 -ErrorAction SilentlyContinue |
  Where-Object { $_.Id -in 1644,36871,36874,1206 } | ForEach-Object { "[$($_.Id)] $($_.Message)" } | Out-String
"CERTDIAG_DONE"
