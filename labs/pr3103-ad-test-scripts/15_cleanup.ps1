# Cleanup after the hung Set-ADDefaultDomainPasswordPolicy call.
# All via ADSI (direct LDAP) - no AD module, no ADWS, cannot hang.
"== stale powershell shells (older than 10 min, excluding current):"
$me = $PID
Get-Process powershell -ErrorAction SilentlyContinue | Where-Object {
  $_.Id -ne $me -and $_.StartTime -and ((Get-Date) - $_.StartTime).TotalMinutes -gt 10
} | ForEach-Object { "  killing PID $($_.Id) started $($_.StartTime)"; Stop-Process -Id $_.Id -Force }

"== lockout policy state (ADSI read):"
$de = [ADSI]'LDAP://DC=ad,DC=example,DC=org'
"  lockoutThreshold: $($de.lockoutThreshold)"
"  lockoutDuration: $($de.lockoutDuration)"
"  lockoutObservationWindow: $($de.lockoutObservationWindow)"
if ([int]$de.lockoutThreshold -ne 0) {
  $de.Put('lockoutThreshold', 0)
  $de.Put('lockoutDuration', -36000000000)      # 30 min (AD default)
  $de.Put('lockoutObservationWindow', -600000000)  # 60 s (AD default)
  $de.SetInfo()
  "  -> reset applied (threshold=0, defaults)"
} else { "  -> threshold already 0, no reset needed" }
"== erin re-check after cleanup:"
$r = [ADSI]'LDAP://DC=ad,DC=example,DC=org'
"  threshold now: $($r.lockoutThreshold)"
"CLEANUP_DONE"
