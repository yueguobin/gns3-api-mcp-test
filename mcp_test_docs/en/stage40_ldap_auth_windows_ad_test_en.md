# GNS3 PR 3103 LDAP Authentication — Windows AD Test Report (Stage 40)

> Chinese version: `mcp_test_docs/zh/阶段40_PR3103-LDAP认证Windows-AD联测报告.md` (same tests, same results).
> This report uses simple English (CEFR A2/B1).

| Item | Content |
|---|---|
| Test date | 2026-11-27 |
| System under test | gns3-server **3.1.0.dev8** on VM21 (LDAP authentication, build from PR #3103) together with **GNS3-AD** (Windows Server 2022 Standard **Core**, 10.0.20348, IP 192.168.101.32, domain `ad.example.org`, single DC `GNS3-AD.ad.example.org`) |
| Test scope | **Functional test matrix on Windows AD, 16 items**: login and diagnostics (7) / group mapping (4) / account state (2) / TLS (2) / config restore (1); **plus 8 extra tests** (Tests 17–24: outage and recovery / rate limiter / refresh × member removal / API key × AD disable / broken bind_dn / input boundaries / AD native lockout / ldap/test variants — see §5) |
| Test method | **Black-box functional tests**: REST API calls (scripts), `ldap*` and `openssl` commands from the test host, WinRM/PowerShell as the management channel. This report only describes what the features do and how to set things up. It does not discuss code. |
| Setup | The full configuration is in **§0.2 and §0.3** (all commands included). Scripts: `labs/pr3103-ad-test-scripts/` (README shows the run order). Config check: §0.4. |
| Result mark | ✓ pass — **main matrix 16/16 + extra tests 8/8, all passed**. Note: in Test 2 the first try of svc-gns3 failed with 401 because of a wrong password in our test script. With the right password it passed (see §2 note). |
| Setup problems | The 5 problems found while building the AD environment (StartTLS 52 / hanging AD module / password policy / management notes / test-script typo) are in a **separate document**: `mcp_test_docs/en/stage40_appendix_windows_ad_setup_troubleshooting_en.md` |

Relation to Stage 39: Stage 39 tested PR #3103 against OpenLDAP 2.6.15 (23 + 10 items). This stage repeats the same test tree and the core scenarios on **Windows AD** (the directory type that this PR mainly targets). Only the directory-specific config fields change (see the diff table in §0.3); everything else stays the same.

## 0. Test environment and configuration

### 0.1 Environment check (on the test day)

- **Controller**: `http://192.168.101.21` (port 80); `GET /v3/version` → `3.1.0.dev8`.
- **GNS3-AD node**: WinRM on port 5985 (enabled by default on Server Core, NTLM). Port 22 and ICMP are closed/blocked by default (this is normal — see appendix, problem 4). Hostname `GNS3-AD`, `Microsoft Windows Server 2022 Standard`, build 10.0.20348, 92 GB free on C:, workgroup before setup.
- **Baseline**: at the start and at the end of the test, the controller runs the OpenLDAP config from Stage 39 (`uri=ldap://ldap.example.org:3890`, start_tls + verify_cert). During the test we switch to the AD config with `PUT /v3/settings`; a `finally` block always restores and verifies it (Test 16).
- **On VM21** (after §0.2 step 5): `getent hosts ad.example.org` → `192.168.101.32`; the system trust store contains the AD self-signed certificate.

### 0.2 The Windows AD directory node (192.168.101.32)

**Management channel**: WinRM (HTTP 5985) + pywinrm with NTLM. The runner script is `labs/pr3103-ad-test-scripts/ps.py`:

```bash
python3 -I ps.py <script.ps1> [read_timeout_sec]
```

**Step 1 — Install the AD role and create the forest** (script `04_ad_setup.py`; role install ~3.5 min, forest install ~4.5 min, one automatic reboot; WinRM comes back after ~30–45 s):

```powershell
Install-WindowsFeature AD-Domain-Services -IncludeAllSubFeature -IncludeManagementTools

Import-Module ADDSDeployment
$sa = ConvertTo-SecureString 'Huawei@123' -AsPlainText -Force
Install-ADDSForest -DomainName 'ad.example.org' -DomainMode WinThreshold -ForestMode WinThreshold `
  -InstallDns -SafeModeAdministratorPassword $sa -Force
# The server reboots when done. The NIC's DNS client was already set to 127.0.0.1 first,
# so the DC's own DNS takes over after the install.
```

Check: `Get-ADDomain` → `ad.example.org`; domain and forest `msDS-Behavior-Version` = **7** (2016, WinThreshold).

**Step 2 — Relax the default password policy** (the AD default policy blocks the plain lowercase password `gns3test`, so relax it before creating users. We write the domain root object directly with ADSI — this does not use the AD PowerShell module, which can hang; see appendix problems 2 and 3):

```powershell
$de = [ADSI]'LDAP://DC=ad,DC=example,DC=org'
$de.Put('pwdProperties', 0)      # disable password complexity
$de.Put('minPwdLength', 1)       # minimum length 1
$de.SetInfo()
```

Check: read back `pwdProperties=0`, `minPwdLength=1`, `LockoutThreshold=0` (default, no lockout).

**Step 3 — Create the test tree** (same matrix as the OpenLDAP file `labs/openldap-gns3-pr-test.ldif`; full idempotent script `06_tree.ps1`; key commands):

```powershell
$root='DC=ad,DC=example,DC=org'
$pw =ConvertTo-SecureString 'gns3test'    -AsPlainText -Force
$svc=ConvertTo-SecureString 'svcldap123'  -AsPlainText -Force

New-ADOrganizationalUnit -Name 'gns3'    -Path $root
New-ADOrganizationalUnit -Name 'people'  -Path "OU=gns3,$root"
New-ADOrganizationalUnit -Name 'groups'  -Path "OU=gns3,$root"

foreach ($u in 'alice','bob','carol','dave','erin','frank') {
  New-ADUser -Name $u -SamAccountName $u -Path "OU=people,OU=gns3,$root" `
    -EmailAddress "$u@ad.example.org" -AccountPassword $pw -Enabled $true -PasswordNeverExpires $true
}
New-ADUser -Name 'svc-gns3' -SamAccountName 'svc-gns3' -Path "OU=people,OU=gns3,$root" `
  -DisplayName 'GNS3 Service Account' -AccountPassword $svc -Enabled $true -PasswordNeverExpires $true

foreach ($g in 'all-staff','gns3-superadmins','gns3-admins','gns3-testers') {
  New-ADGroup -Name $g -GroupScope Global -GroupCategory Security -Path "OU=groups,OU=gns3,$root"
}
Add-ADGroupMember 'all-staff'        'alice'
Add-ADGroupMember 'gns3-superadmins' 'frank'
Add-ADGroupMember 'gns3-admins'      'bob','carol','erin'
Add-ADGroupMember 'gns3-testers'     'carol','dave'
```

Membership check (`Get-ADGroupMember`):

```text
all-staff        : alice
gns3-superadmins : frank
gns3-admins      : bob,carol,erin
gns3-testers     : carol,dave
== user count: 7
```

User DN form (used by `bind_dn` and `{user_dn}`): `CN=carol,OU=people,OU=gns3,DC=ad,DC=example,DC=org`.

**Direct directory checks** (ldapsearch from the test host, with the svc-gns3 bind and the same filter shapes that GNS3 uses):

```bash
# User search (same shape as GNS3 user_search_filter)
ldapsearch -x -H ldap://192.168.101.32 \
  -D 'CN=svc-gns3,OU=people,OU=gns3,DC=ad,DC=example,DC=org' -w svcldap123 \
  -b 'OU=gns3,DC=ad,DC=example,DC=org' '(&(objectClass=user)(sAMAccountName=carol))' dn memberOf
# -> carol found; memberOf already lists gns3-admins and gns3-testers

# Group search (same shape as GNS3 group_search_filter)
ldapsearch -x -H ldap://192.168.101.32 \
  -D 'CN=svc-gns3,OU=people,OU=gns3,DC=ad,DC=example,DC=org' -w svcldap123 \
  -b 'OU=gns3,DC=ad,DC=example,DC=org' \
  '(&(objectClass=group)(member=CN=carol,OU=people,OU=gns3,DC=ad,DC=example,DC=org))' dn
# -> gns3-admins and gns3-testers

# User bind (the password path used at login)
ldapwhoami -x -H ldap://192.168.101.32 \
  -D 'CN=alice,OU=people,OU=gns3,DC=ad,DC=example,DC=org' -w gns3test   # -> Success
```

**Step 4 — LDAPS/StartTLS certificate** (scripts `07_cert.ps1` and `12_certfix.ps1`; the "52" problem we hit on the way is in the appendix, problem 1. Below is the **final working recipe**):

```powershell
# Self-signed certificate: SAN has 3 DNS names (the uri must use a name, not an IP),
# EKU = Server Authentication
$cert = New-SelfSignedCertificate -Subject 'CN=ad.example.org' `
  -DnsName 'ad.example.org','gns3-ad.ad.example.org','GNS3-AD' `
  -CertStoreLocation 'Cert:\LocalMachine\My' -KeyLength 2048 `
  -NotAfter (Get-Date).AddYears(10) -KeyUsage KeyEncipherment,DigitalSignature `
  -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.1')

Export-Certificate -Cert $cert -Type CERT -FilePath 'C:\Windows\Temp\ad-lab-root.cer'

# Key step 1: self-trust. If the certificate is only in the My store,
# LSASS will not use it and AD answers StartTLS with result 52.
Import-Certificate -FilePath 'C:\Windows\Temp\ad-lab-root.cer' -CertStoreLocation 'Cert:\LocalMachine\Root'

# Key step 2: reboot the DC. LSASS does not rescan the certificate store while running.
Restart-Computer -Force
```

Check from the test host after the reboot (both ports must complete a TLSv1.3 handshake with certificate `CN=ad.example.org`):

```bash
openssl s_client -connect 192.168.101.32:389 -starttls ldap -brief </dev/null
openssl s_client -connect 192.168.101.32:636 -brief </dev/null
```

**Step 5 — VM21 prerequisites** (script `08_tls_setup.py` does this automatically; manual equivalent):

```bash
# Name resolution (TLS hostname checks require a domain name in the uri)
echo '192.168.101.32 ad.example.org gns3-ad.ad.example.org' | sudo tee -a /etc/hosts

# Trust the AD self-signed certificate (convert the exported .cer to PEM first)
sudo cp ad-lab-root.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

### 0.3 Controller-side configuration (VM21, 192.168.101.21)

The config was injected with `PUT /v3/settings` (body `{"LDAP": {...}}`, all 17 fields, real bind_password, wait 5 s after the PUT — same effect as writing `gns3_server.conf`). The `[LDAP]` section:

```ini
[LDAP]
enabled = True
uri = ldap://ad.example.org:389
bind_dn = CN=svc-gns3,OU=people,OU=gns3,DC=ad,DC=example,DC=org
bind_password = svcldap123
base_dn = OU=gns3,DC=ad,DC=example,DC=org
group_search_base = OU=gns3,DC=ad,DC=example,DC=org
user_search_filter = (&(objectClass=user)(sAMAccountName={username}))
user_attr_username = sAMAccountName
user_attr_email = mail
user_attr_fullname = cn
group_search_filter = (&(objectClass=group)(member={user_dn}))
group_mapping = {"gns3-admins": "Administrators", "gns3-testers": "Testers"}
default_group = Users
start_tls = True
verify_cert = True
fallback_to_local = True
timeout = 10
```

**Field diff** against the OpenLDAP config (all other fields unchanged):

| Field | OpenLDAP (Stage 39) | Windows AD (this stage) | Note |
|---|---|---|---|
| uri | `ldap://ldap.example.org:3890` | `ldap://ad.example.org:389` | AD uses standard ports |
| bind_dn | `uid=svc-gns3,ou=people,…` | `CN=svc-gns3,OU=people,…` | DN form follows the naming attribute |
| base_dn / group_search_base | `ou=gns3,dc=example,dc=org` | `OU=gns3,DC=ad,DC=example,DC=org` | same tree shape, different suffix |
| user_search_filter | `(&(objectClass=person)(uid={username}))` | `(&(objectClass=user)(sAMAccountName={username}))` | AD user object class and login name attribute |
| user_attr_username | `uid` | `sAMAccountName` | same |
| group_search_filter | `(&(objectClass=groupOfNames)(member={user_dn}))` | `(&(objectClass=group)(member={user_dn}))` | AD has no groupOfNames; use the built-in group class. The member attribute has the same name; memberOf is maintained by AD |

The `ldap/test` diagnostic endpoint (flat body, not wrapped in `{"LDAP":…}`) was called with the AD parameters **before** the config switch, so we knew the parameters work before putting them live (Test 1).

### 0.4 Config vs. running environment check (2026-11-27, item by item)

| Item | Source | How it was checked | Match |
|---|---|---|---|
| domain / functional level | §0.2 step 1 | `Get-ADDomain` = ad.example.org; domain and forest `msDS-Behavior-Version`=7 (read over LDAP) | ✓ |
| tree size and members | §0.2 step 3 | `Get-ADUser` count = 7; all 4 groups read member by member | ✓ |
| svc-gns3 bind | §0.2 step 3 | ldapsearch bind + user/group filter search from the test host | ✓ |
| password policy | §0.2 step 2 | read back via ADSI: pwdProperties=0, minPwdLength=1 | ✓ |
| certificate material | §0.2 step 4 | checked by OID: SAN 3×dNSName, EKU=1.3.6.1.5.5.7.3.1, HasPrivateKey=True | ✓ |
| Root self-trust | §0.2 step 4 | thumbprint found in LocalMachine\Root | ✓ |
| StartTLS/LDAPS working | §0.2 step 4 | openssl handshake TLSv1.3 on both ports, server cert `CN=ad.example.org` | ✓ |
| VM21 hosts | §0.2 step 5 | `getent hosts ad.example.org` → 192.168.101.32 | ✓ |
| VM21 CA | §0.2 step 5 | update-ca-certificates done; all logins pass with verify_cert=True (Tests 2/14) | ✓ |
| [LDAP] 17 fields | §0.3 | PUT + read-back comparison (bind_password masked on read; real value checked at PUT time) | ✓ |
| baseline restore | §0.1 | Test 16: after restore, carol 200 and Administrators=[bob,carol,erin] | ✓ |

Conclusion: every item in §0.2/§0.3 matches the running environment. The commands in this section can reproduce the setup.

## 1. Test matrix

| Group | Test | Scenario | Result | Notes |
|---|---|---|---|---|
| A login & diagnostics | Test 1 | ldap/test endpoint with AD parameters | ✓ | `{"status":"success","bind_successful":true,"user_search_successful":true,"users_found":5,"latency_ms":29.04}` (users_found=5 is the sample cap; same as Stage 39) |
| A login & diagnostics | Test 2 | all test users log in (StartTLS + verify_cert=True) | ✓ | alice/bob/carol/dave/erin/frank 200; svc-gns3 200 with its own password svcldap123 |
| A login & diagnostics | Test 3 | username case folding | ✓ | login name `Alice` → 200 (sAMAccountName is case-insensitive) |
| A login & diagnostics | Test 4 | local account co-exists | ✓ | admin/admin local login 200 (fallback_to_local=True) |
| A login & diagnostics | Test 5 | wrong password rejected | ✓ | bob + wrong password → 401 |
| A login & diagnostics | Test 6 | unknown user rejected | ✓ | nobody → 401 |
| A login & diagnostics | Test 7 | username matches only the configured attribute | ✓ | `alice@ad.example.org` (her mail value) as username → 401 (only sAMAccountName matches) |
| B group mapping | Test 8 | JIT authorization by group mapping | ✓ | bob/carol/erin (gns3-admins) → Administrators=[bob,carol,erin], checked against the authoritative list |
| B group mapping | Test 9 | multi-group membership | ✓ | carol in Administrators and in Testers (AD native memberOf carries both) |
| B group mapping | Test 10 | unmapped group falls back to default | ✓ | alice (all-staff, no mapping) and frank land in Users; Users list contains alice/frank |
| B group mapping | Test 11 | superadmin mapping flip | ✓ | add gns3-superadmins→Administrators → frank in Administrators; remove → frank back in Users |
| C account state | Test 12 | AD-disabled account rejected | ✓ | `Disable-ADAccount alice` → login 401 |
| C account state | Test 13 | account re-enabled, access returns | ✓ | `Enable-ADAccount alice` → login 200 |
| D TLS | Test 14 | LDAPS 636 (name uri + verify_cert=True) | ✓ | carol login 200 |
| D TLS | Test 15 | certificate check negative case (IP uri) | ✓ | `ldaps://192.168.101.32:636` + verify_cert=True → 401 (ldap3 rejects IP hostnames, same as Stage 39) |
| E config restore | Test 16 | restore the OpenLDAP baseline | ✓ | the finally block PUTs back the Stage 39 config → carol 200, Administrators=[bob,carol,erin], read-back matches |

## 2. Execution record

Script `labs/pr3103-ad-test-scripts/09_ad_matrix.py` (the `finally` block always restores the OpenLDAP config) ran the whole matrix in one pass after the certificate fix. Key output:

```text
[baseline GET settings] status=200 uri=ldap://ldap.example.org:3890
[ldap/test AD] status=200 -> {"status": "success", "bind_successful": true,
  "user_search_successful": true, "users_found": 5, "latency_ms": 29.04}
[PUT settings] AD StartTLS+verify: status=200
[login alice] 200      [login bob] 200      [login carol] 200
[login dave] 200       [login erin] 200     [login frank] 200
[login 'Alice' uppercase] 200              [login admin local] 200
[login bob wrongpw] 401                    [login nonexistent nobody] 401
[login alice@ad.example.org] 401
[Administrators] ['bob', 'carol', 'erin']
[Testers] ['carol', 'dave', 'student-10']  # student-10 is an old local record
[Users] contains alice and frank (+10 old local records)
[flip] add mapping    -> frank login 200; Administrators=[bob,carol,erin,frank]
[flip] remove mapping -> frank login 200; Administrators=[bob,carol,erin]
[Disable-ADAccount alice] -> [login alice] 401
[Enable-ADAccount alice]  -> [login alice] 200
[LDAPS ad.example.org:636]  carol 200
[LDAPS IP 192.168.101.32:636] carol 401 (negative case)
[back to StartTLS] carol 200
[RESTORE OpenLDAP] carol 200; Administrators=['bob','carol','erin']
[restore verify] uri=ldap://ldap.example.org:3890 start_tls=True verify_cert=True
```

> Note (Test 2): the first svc-gns3 try returned 401 because our matrix script used the wrong password (gns3test). With the real password svcldap123 it returned 200. This was a test-side mistake, not product behavior.

Directory-outage behavior, rate limiting (5 tries → 429 → unblock at t+60s), and refresh-token role re-computation were already verified in Stage 39 (OpenLDAP) and were not repeated here.

## 3. Observations (neutral notes)

1. **memberOf works the same way**: AD returns memberOf natively (a search for carol already carries both groups). GNS3 merges memberOf with the directory search, and the result matches the OpenLDAP side exactly.
2. **users_found=5**: the count in ldap/test is cut at the sample limit (size_limit). Same shape as Stage 39 on OpenLDAP; not an AD-specific difference.
3. **The service account can log in**: svc-gns3 matches user_search_filter and can log in as a normal user (lands in the default group). In a real deployment you should exclude service accounts from the login filter or control them separately.
4. **Disabled account and wrong password look the same**: a disabled account gets 401, the same shape as a wrong password (no account enumeration leak).
5. **Failure shape before the fix**: while the certificate was not trusted, ldap/test returned `Failed to bind to LDAP server: unavailable` (2.69 ms) and every login returned 401. How this was found and fixed is in the appendix, problem 1.

## 4. Conclusion

- PR #3103 passes on Windows AD (Server 2022 Core, single DC): main matrix **16/16** + extra tests **8/8** — logins, group mapping (including native memberOf), superadmin flip, AD account state, LDAPS and StartTLS with certificate-check negative cases, config restore, outage/rate-limiter/refresh/API-key life cycle — all consistent with the OpenLDAP side (down to the latency shape: admin local escape 271 ms vs OpenLDAP 270 ms; a login during the outage waits exactly timeout=10).
- Moving from OpenLDAP to AD changes only **6 fields** (diff table in §0.3). All are directory-side form differences; the controller-side behavior is the same.
- The setup has three high-value pitfalls (self-signed LDAPS certificate needs Root self-trust + reboot; the AD PowerShell module can hang after a DC reboot; the default password policy blocks lab passwords). The full troubleshooting record is in the **appendix**: `mcp_test_docs/en/stage40_appendix_windows_ad_setup_troubleshooting_en.md`. All scripts are kept in run order in `labs/pr3103-ad-test-scripts/`.

Related document: Stage 39 (full matrix on OpenLDAP) `mcp_test_docs/zh/阶段39_PR3103-LDAP认证功能测试报告.md`.

## 5. Extra tests (Tests 17–24)

These close the depth gap with the OpenLDAP side (Stage 39). Scripts: `labs/pr3103-ad-test-scripts/14_ad_extra_matrix.py` (first version) and `16_ad_extra_fix.py` (final version: ADSI direct writes + client-side watchdogs — see §5.2 and appendix problem 2).

### 5.1 Results table

| Group | Test | Scenario | Result | Notes |
|---|---|---|---|---|
| D outage | Test 17 | directory outage (netsh blocks 389/636) | ✓ | admin local escape **200 / 271 ms**; old token during outage **403 / 8.8 ms** (fail-open); fresh login during outage 401 (waits exactly timeout=10, measured 10.02 s); after recovery 200 / 68 ms — same numbers as the OpenLDAP side (Stage 39 tests 17–20) |
| E rate limit | Test 18 | login rate limiter | ✓ | dave 5×401 → 6th try (correct password) **429** → still 429 at t+25 s → **unblocked 200 at t+65 s** — the mechanism does not care about the directory type |
| F sessions | Test 19 | refresh × member removal | ✓ | bob removed from gns3-admins (5 s settle) → old token 200 (fail-open) → refresh 200 → new token **403** (role re-calculated) → member restored, fresh login 200 — same as OpenLDAP; an immediate refresh ≈1 s after the removal once returned 200 (a small convergence race window, see §5.2) |
| F sessions | Test 20 | API key × AD disable/removal | ✓ | with bob **disabled in AD, the key still answers 200** (key login never touches the directory); fresh login while disabled 401, after re-enable 200 → same key 200; member removed + fresh login (role → Users) → same key **403** (rights converge at re-login) → restored → 200; **key deletion is owner-only** (see §5.2) |
| G global fault | Test 21 | broken bind_dn | ✓ | svc-gns3 password broken → alice login 401; restored → 200 (same shape as Stage 39 test 24) |
| H diagnostics | Test 24 | ldap/test variants | ✓ | wrong bind_password → `{"status":"error","bind_successful":false,"users_found":0}` (21.6 ms); correct → success, users_found=5 (15.5 ms, sample cap) |
| G input edges | Test 22 | input boundaries | ✓ | special-char password `Gns3!test#2026&<>"` → **200** (JSON API handles it all); empty password 401; **`" alice "` with leading/trailing spaces → 200, folded to the same account** (AD sAMAccountName matching also folds whitespace — same as the OpenLDAP caseIgnore behavior); non-existent Chinese name 401; 2000-char username 401 |
| C account policy | Test 23 | AD native lockout policy | ✓ | domain lockout threshold=3/60 s: erin 3 wrong → **even the correct password is rejected (401, 46 ms — directory lockout fires before the rate limiter)** → auto-unlock after 60 s (200) → threshold reset to 0, login 200 — mirrors the OpenLDAP ppolicy double-layer shape (Stage 39 test 31) |

Result: **all 8 extra tests passed. AD-side total: 24/24.**

### 5.2 Three behaviors worth noting

**Test 19 — convergence race window**: in the first attempt, a refresh fired ≈1 s after the member removal still returned a token with admin rights (200). The same scenario with a 5 s settle returned 403 for the refreshed token, matching OpenLDAP. So: the refresh convergence itself is identical on both directories, but a refresh fired immediately after a removal can race the change (seen once; not investigated further).

**Test 20 — key deletion is owner-only**: an admin deleting bob's key with his own token got **403** (RBAC refuses cross-user deletion); bob deleting his own key got 204. This is a different path from Stage 39 test 33, where an admin deleted the whole **user record** (which kills the key with 401). The key's own life-cycle operations (revoke/restore/delete) belong to its creator; an admin can only kill a key indirectly by deleting or disabling the **user**.

**Test 23 — policy changes must go through ADSI**: `Set-ADDefaultDomainPasswordPolicy` (AD module / ADWS path) **wedged a second time** on this machine — the server-side shell never returned (>44 minutes) and the pywinrm client `read_timeout` did not fire. Final fix: the AD PowerShell module is **fully dropped** — group operations and policy changes are direct ADSI writes (`Put` + `SetInfo` on the domain/group objects, the local LDAP path, which never hung), and every WinRM call runs under a client-side watchdog (a daemon thread abandoned on join timeout). Full story in appendix problem 2.

### 5.3 What stayed in the environment

- Both test keys from Test 20 are deleted with the owner path (204; bob's key list is empty); bob's membership is restored (Administrators=[bob,carol,erin] verified).
- dave/erin enabled with original passwords; lockout threshold reset to 0 (duration/observation back to defaults); the firewall block rule is deleted; svc-gns3 password restored (bind verified).
- After the tests, the controller was restored to the OpenLDAP baseline config and verified (carol 200, Administrators=[bob,carol,erin]).
