$ErrorActionPreference = 'Stop'
$cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object {$_.Subject -match 'ad\.example\.org'} | Select-Object -First 1
if (-not $cert) {
  $cert = New-SelfSignedCertificate -Subject 'CN=ad.example.org' -DnsName 'ad.example.org','gns3-ad.ad.example.org','GNS3-AD' -CertStoreLocation 'Cert:\LocalMachine\My' -KeyLength 2048 -NotAfter (Get-Date).AddYears(10) -KeyUsage KeyEncipherment,DigitalSignature -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.1')
  "cert created"
} else { "cert already present" }
"thumb: $($cert.Thumbprint)  notAfter: $($cert.NotAfter)"
$san = $cert.Extensions | Where-Object {$_.Oid.FriendlyName -match 'Subject Alternative Name'}
if ($san) { "san:"; $san.Format($false) }
Export-Certificate -Cert $cert -Type CERT -FilePath 'C:\Windows\Temp\ad-lab-root.cer' | Out-Null
certutil -encode 'C:\Windows\Temp\ad-lab-root.cer' 'C:\Windows\Temp\ad-lab-root.b64' | Out-Null
"b64 bytes: $((Get-Item 'C:\Windows\Temp\ad-lab-root.b64').Length)"
"== 636 reachable locally: $((Test-NetConnection -ComputerName 127.0.0.1 -Port 636 -WarningAction SilentlyContinue).TcpTestSucceeded)"
"== 389 reachable locally: $((Test-NetConnection -ComputerName 127.0.0.1 -Port 389 -WarningAction SilentlyContinue).TcpTestSucceeded)"
"CERT_OK"
