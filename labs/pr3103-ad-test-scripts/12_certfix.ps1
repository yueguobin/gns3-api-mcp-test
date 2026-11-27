$ErrorActionPreference = 'Continue'
$cert = Get-ChildItem Cert:\LocalMachine\My | Where-Object {$_.Thumbprint -eq '0EE8545BFAE4EE7CA5A11471AC32854C0082EF86'} | Select-Object -First 1
if (-not $cert) { "CERT NOT FOUND IN My"; exit 1 }

"== raw extensions by OID (locale-independent):"
foreach ($e in $cert.Extensions) {
  "OID $($e.Oid.Value) critical=$($e.Critical)"
  $e.Format($false) -split "`n" | ForEach-Object { "   $_" }
}
"HasPrivateKey: $($cert.HasPrivateKey)  KeyAlgo: $($cert.PublicKey.Oid.FriendlyName)/$($cert.PublicKey.Oid.Value)  SigAlgo: $($cert.SignatureAlgorithm.Value)"

"== self-trust: export from My, import to LocalMachine\Root:"
$cerFile = 'C:\Windows\Temp\ad-lab-root.cer'
Export-Certificate -Cert $cert -Type CERT -FilePath $cerFile | Out-Null
$rootStore = Get-ChildItem Cert:\LocalMachine\Root | Where-Object {$_.Thumbprint -eq $cert.Thumbprint}
if (-not $rootStore) {
  Import-Certificate -FilePath $cerFile -CertStoreLocation 'Cert:\LocalMachine\Root' | Out-Null
  "imported to Root"
} else { "already in Root" }
"Root store check: $((Get-ChildItem Cert:\LocalMachine\Root | Where-Object {$_.Thumbprint -eq $cert.Thumbprint}).Count) found"
"CERTFIX_DONE"
