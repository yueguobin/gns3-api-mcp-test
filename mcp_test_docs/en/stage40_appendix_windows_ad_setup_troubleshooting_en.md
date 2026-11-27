# Windows AD Setup — Troubleshooting Notes (Stage 40 Appendix)

> Chinese version: `mcp_test_docs/zh/阶段40附录_Windows-AD环境搭建问题排查记录.md` (same content).
> This document uses simple English (CEFR A2/B1).

| Item | Content |
|---|---|
| Date | 2026-11-27 |
| Environment | GNS3-AD: Windows Server 2022 Standard **Core** (10.0.20348), 192.168.101.32, single DC for domain `ad.example.org`; management channel WinRM 5985 + pywinrm (NTLM) |
| Nature | **Environment setup problems only.** They have nothing to do with gns3-server or PR #3103. We record the symptoms, how we narrowed them down, the root causes and the fixes, so others can reproduce the setup faster |
| Related | Main report: `mcp_test_docs/en/stage40_ldap_auth_windows_ad_test_en.md`; scripts: `labs/pr3103-ad-test-scripts/` (kept in run order, including the diagnostic scripts) |

---

## Problem 1: AD answers StartTLS with LDAP result 52 (unavailable) — LSASS refuses the self-signed certificate

**This was the biggest time sink of this setup.** Three rounds of checks.

### Symptoms

- The certificate (self-signed, with SAN, Server-Auth EKU, private key) is in `LocalMachine\My`; ports 389 and 636 are listening;
- GNS3 `ldap/test` fails at once: `{"status":"error","bind_successful":false,...,"message":"Failed to bind to LDAP server: unavailable","latency_ms":2.69}`; every login returns 401;
- Raw ldap3 fails with **both** `CERT_REQUIRED` and `CERT_NONE`: `LDAPStartTLSError: startTLS failed - unavailable`. So this is not a certificate-validation problem — the server refuses before any certificate check.

### How we narrowed it down

| Step | Command | Result | Conclusion |
|---|---|---|---|
| 1. VM21 network | `getent hosts ad.example.org`; `bash -c 'cat < /dev/null > /dev/tcp/ad.example.org/389'` | resolution OK, TCP OK | rules out DNS, routing, firewall |
| 2. raw ldap3, both modes | on VM21, same venv as gns3server (`ldap3.Tls(validate=...)`) | `CERT_REQUIRED` and `CERT_NONE` both fail with `startTLS failed - unavailable` | rules out the certificate-validation layer |
| 3. openssl probe | `openssl s_client -connect 192.168.101.32:389 -starttls ldap -brief` | **`STARTTLS failed, LDAP Result Code: 52`** | hard proof: the server answers the StartTLS request itself with 52 (unavailable) |
| 4. Schannel events | `Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Schannel'}` | **event 36886 every 10 seconds** ("no credentials available in the security package"; times match our probes exactly) | LSASS believes there is no usable server certificate |
| 5. certificate check | enumerate extensions **by OID** (see problem 4 for why) | SAN = 3×dNSName, EKU = 1.3.6.1.5.5.7.3.1, HasPrivateKey = True | the certificate itself is fine |

### Root cause

**The self-signed certificate was only in `LocalMachine\My`, with no trusted chain.** When LSASS picks a certificate for server authentication, the chain must build up to a trusted root. A self-signed certificate that is not in a trusted store fails chain building → it is not selected as a server credential (event 36886) → the LDAP service answers StartTLS/LDAPS with 52 (unavailable).

### Fix (both steps are required)

```powershell
# Step 1: self-trust. Import the same certificate into the trusted root store.
Import-Certificate -FilePath 'C:\Windows\Temp\ad-lab-root.cer' -CertStoreLocation 'Cert:\LocalMachine\Root'

# Step 2: reboot the DC. LSASS does not rescan the certificate store while running.
Restart-Computer -Force
```

### Verification after the fix

- `openssl s_client -starttls ldap` → `CONNECTION ESTABLISHED`, `Protocol version: TLSv1.3`, `depth=0 CN=ad.example.org`;
- LDAPS on 636 also TLSv1.3;
- the whole GNS3 matrix (ldap/test, then 16 items of login/mapping/TLS) passed in one run (main report §2).

### Lessons

1. If GNS3 says `Failed to bind: unavailable` with a near-zero latency, and it still fails with CERT_NONE, suspect the server TLS first. One `openssl s_client -starttls ldap` call gives the answer (result code 52).
2. The recipe for a self-signed LDAPS certificate on a DC = **My store (with private key) + Root store (self-trust) + reboot**. All three are needed. Common guides that say "My store is enough" did not work here.
3. When checking certificate extensions, match by **OID value** (2.5.29.17 / 2.5.29.37), never by FriendlyName (see problem 4).

---

## Problem 2: AD PowerShell module calls hang forever after a DC reboot

### Symptoms

- About 1 minute after the `Install-ADDSForest` reboot, WinRM answers again (light commands return at once; services NTDS/kdc/DNS/ADWS all show Running);
- But the next verification script (`Get-ADDomain` → `Set-ADDefaultDomainPasswordPolicy`) **hung for 27 minutes** with no return;
- New probe calls were also very slow or hung (>120 s), so the problem looked worse each time we checked.

### How we narrowed it down

- Light `Get-Service` queries returned at once → WinRM and PowerShell themselves were fine;
- Counting powershell processes on the server found a **zombie shell from the call made right after the reboot** (PID 1692, started 10:41:26). Our client had been killed by a timeout, but the server-side command was still running without any timeout.

### Root cause

Calls to the AD module (`Get-ADDomain` and friends) made while **ADWS is not ready yet** (right after a DC reboot) wait forever. The hanging session stays on the server and drags down later calls too.

### How to avoid it

1. Wrap every AD-module call in a **server-side watchdog** (bounded time; never hangs the connection):

```powershell
$job = Start-Job { Import-Module ActiveDirectory; (Get-ADDomain).DNSRoot }
if (Wait-Job $job -Timeout 120) { Receive-Job $job } else { "still hangs"; Stop-Job $job }
```

2. **Clean up zombie shells** (excluding the current session):

```powershell
Get-Process powershell | Where-Object {
  $_.Id -ne $PID -and $_.StartTime -and ((Get-Date) - $_.StartTime).TotalMinutes -gt 15
} | Stop-Process -Force
```

3. In the run book: after a reboot, wait for NTDS/kdc/ADWS to settle (about 2–3 minutes here), probe with the watchdog, and only then run normal calls.

In our case, after the cleanup, `Get-ADDomain` returned `ad.example.org` immediately.

---

## Problem 3: the default password policy rejects the lab passwords

### Symptom / why we acted early

The AD default domain policy has **complexity enabled + minimum length 7**. The lab password `gns3test` (all lowercase) cannot pass; `svcldap123` also fails. To keep the same passwords as the OpenLDAP stage, we relaxed the policy before creating users.

### Fix

Two equivalent ways. **ADSI is preferred** (it does not use the AD module, so it avoids the hang area of problem 2):

```powershell
# Way A: write the domain root object directly with ADSI (used in this setup)
$de = [ADSI]'LDAP://DC=ad,DC=example,DC=org'
$de.Put('pwdProperties', 0)     # disable complexity
$de.Put('minPwdLength', 1)
$de.SetInfo()

# Way B: AD module (uses ADWS; same effect)
Set-ADDefaultDomainPasswordPolicy -ComplexityEnabled:$false -MinPasswordLength 1
```

Check: `pwdProperties=0`, `minPwdLength=1`, `LockoutThreshold=0` (default, no lockout — this keeps the negative tests unaffected).

> Lab setting only. Never disable complexity in a production domain.

---

## Problem 4: management-channel and environment notes

| Item | Symptom | Note / handling |
|---|---|---|
| Server Core has no SSH | port 22 not installed | the management channel is **WinRM 5985** (enabled by default on Server Core, NTLM). SSH can be added over WinRM via the `OpenSSH.Server` capability; we did not need it |
| ping fails | ICMP echo 100% loss | the Windows firewall blocks echo by default. **This does not mean the node is down**; probe ports instead |
| pywinrm install | system python blocked `--user` (PEP 668) | installed into the system python (done by the user); all scripts run with `python3 -I` |
| PowerShell is slow | role install 3.5 min, forest install 4.5 min, some calls tens of seconds | normal for a 1-vCPU VM; run long tasks as background scripts with a log file |
| Chinese-locale FriendlyName | certificate extensions matched by English names (like `Subject Alternative Name`) all returned null | .NET `Oid.FriendlyName` follows the system language. **Always match by `Oid.Value` (the raw OID string)** |
| meaning of the ldap/test message | `Failed to bind to LDAP server: unavailable` | `unavailable` is the ldap3 result description passed through by the controller (LDAP 52). It does **not** mean "network unreachable" — in our case the network layer was fully working |

---

## Problem 5: a wrong password in our test script (test-side, not an environment problem)

The matrix script used the wrong password for svc-gns3 (gns3test instead of svcldap123), so the first matrix run showed svc-gns3 login 401. With the correct password it returned 200. This is noted in the main report §2, and here, so nobody reads it as product behavior later.
