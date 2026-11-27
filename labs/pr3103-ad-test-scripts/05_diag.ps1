$ErrorActionPreference = 'Continue'
"== stale powershell cleanup (older than 15 min, excluding current):"
$me = $PID
Get-Process powershell -ErrorAction SilentlyContinue | Where-Object {
  $_.Id -ne $me -and $_.StartTime -and ((Get-Date) - $_.StartTime).TotalMinutes -gt 15
} | ForEach-Object { "  killing PID $($_.Id) started $($_.StartTime)"; Stop-Process -Id $_.Id -Force }

"== Get-ADDomain under server-side watchdog (120s):"
$job = Start-Job { Import-Module ActiveDirectory; (Get-ADDomain).DNSRoot }
if (Wait-Job $job -Timeout 120) { "  ADDomain OK: $(Receive-Job $job)" } else { "  ADDomain HANGS (watchdog fired)"; Stop-Job $job -ErrorAction SilentlyContinue }
Remove-Job $job -Force -ErrorAction SilentlyContinue

"== password policy via ADSI (bypasses ADWS):"
$de = [ADSI]'LDAP://DC=ad,DC=example,DC=org'
try {
  $de.Put('pwdProperties', 0)
  $de.Put('minPwdLength', 1)
  $de.SetInfo()
  "  policy set OK: pwdProperties=$($de.pwdProperties.ToString()) minPwdLength=$($de.minPwdLength.ToString())"
} catch { "  POLICY ERR: $($_.Exception.Message)" }

"== levels via LDAP root:"
$dom = [ADSI]'LDAP://DC=ad,DC=example,DC=org'
"  domain msDS-Behavior-Version: $($dom.'msDS-Behavior-Version'.ToString())"
$cfg = [ADSI]'LDAP://CN=Partitions,CN=Configuration,DC=ad,DC=example,DC=org'
"  forest msDS-Behavior-Version: $($cfg.'msDS-Behavior-Version'.ToString())"
"DIAG_DONE"
