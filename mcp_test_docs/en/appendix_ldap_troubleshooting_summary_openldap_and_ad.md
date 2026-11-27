# LDAP Integration — Troubleshooting Summary: OpenLDAP × Windows AD (cross-stage appendix)

> Chinese version: `mcp_test_docs/zh/附录_LDAP联测问题排查汇总_OpenLDAP与WindowsAD.md` (same content).
> This document uses simple English (CEFR A2/B1).

| Item | Content |
|---|---|
| Scope | All integration tests, stages 38–40 (2026-11-24 to 11-27): a **summary and comparison of directory-side / environment-side problems**. gns3-server code issues are out of scope (see the stage reports and PR comments) |
| Why one document | The problems on the two directory types (OpenLDAP 2.6.15 container / Windows AD 2022 Core, single DC) are **very similar in nature** — TLS trust chains, attribute visibility, hangs, account lockout — so they are collected and compared in one place |
| Related | OpenLDAP details: Stage 38 (§6 runbook) / Stage 39 report; AD details: `mcp_test_docs/en/stage40_appendix_windows_ad_setup_troubleshooting_en.md`; scripts: `labs/pr3103-retest-scripts/`, `labs/pr3103-ad-test-scripts/` |

---

## 1. OpenLDAP-side problems (stages 38–39)

| # | Problem | Symptom | Root cause | Fix / workaround |
|---|---|---|---|---|
| 1 | container crash loop (v2 image) | openldap 2.6.15 container exits with code 1 in a loop ("This account is not available") | the GNS3 docker wrapper init.sh runs `su $GNS3_USER`, but the v2 image declares `User=ldap` with shell `/sbin/nologin` | upstream fix PR #3108: fall back to `su -s /bin/sh` when the shell is nologin. **After switching branches or redeploying, run `grep SU_SHELL_ARG init.sh` before starting docker nodes** (it came back once) |
| 2 | container rebuild loses data | after a rebuild the directory keeps only the base entries; eth0 has no IPv4 | non-persistent volumes + the injected init.sh network template is fully commented out (configures nothing) | three persistent volumes (data/slapd.d/backups) + a one-shot runbook to re-import LDIF/ACL/TLS |
| 3 | default ACL blocks all reads | svc-gns3 can bind but every search returns 32 (No such object) | the default `{1}mdb` rule 2 is `by * none` | on 1.5.0: change to `by users read`; on 2.6.15: attribute whitelist (see #4) |
| 4 | group resolution blocked by ACL | mapped groups come out empty | the 2.6.15 v2 default `{2}` attribute whitelist has **no member**, so `(member=…)` matches are cut off by `{3} by * none` | `labs/openldap26-acl-member-read.ldif`: append member to the {2} attrs |
| 5 | filter attribute invisible | after adding a description condition to the filter, **even marked users get 401** | attributes used in the filter must be readable by bind_dn — description was not in the {2} whitelist, so it matched as "not present" | `labs/openldap26-acl-description-read.ldif`: append description to the {2} attrs (Stage 39 test 34, proven both ways) |
| 6 | TLS hostname check | `verify_cert=True` with an IP-shaped uri always fails | ldap3 2.9.1 on py≥3.12 match_hostname accepts **only dNSName SANs** (CN is not checked when a DNS SAN exists); an IP never matches | always use a domain name in the uri + DNS names in the SAN; the IP uri becomes the negative test case |
| 7 | TLS certificate placement | writing olcTLS* on the frontend database entry fails with error 65 | TLS attributes live on the **cn=config global entry**, not on database entries | certificate into the persistent volume (owner 911 / mode 600) + `docker cp` + the three olcTLS* attributes on the global entry; VM21 gets the CA and a hosts entry |
| 8 | ppolicy setup traps | policy entry cannot be created / olcPPolicyDefault cannot be written / module cannot be unloaded | pwdPolicy is an auxiliary class and needs an organizationalRole structural class; olcPPolicyDefault needs an **active overlay** (attributes register dynamically); olcModuleLoad cannot be removed at runtime (error 80, harmless leftover) | the image ships the cn={4}ppolicy schema, no import needed; recipe = module + overlay + policy entry + pwdPolicySubentry (Stage 39 test 31) |
| 9 | half-dead timeout shape | after `docker pause`, logins hang | application dead but the port still open | the configured timeout=10 catches it: the login waits exactly 10.02 s and returns 401; unpause recovers at once |
| 10 | uid case folding | the uppercase uid=Alice entry cannot be created (Already exists) | caseIgnore matching folds the case | the case scenario is triggered by the login string; the directory cannot hold two DNs |

## 2. Windows AD-side problems (stage 40)

| # | Problem | Symptom | Root cause | Fix / workaround |
|---|---|---|---|---|
| 1 | StartTLS always refused (**the biggest time sink**) | GNS3 reports `Failed to bind: unavailable` (2.69 ms); it still fails with CERT_NONE; openssl proves `STARTTLS failed, LDAP Result Code: 52` | the self-signed certificate was only in the My store, so the chain does not build → LSASS refuses it as a server credential (Schannel event 36886 every 10 s) | **also import the certificate into LocalMachine\Root (self-trust) + reboot the DC** (LSASS does not rescan while running); check certificate extensions by OID value (on a Chinese-locale system FriendlyNames are localized) |
| 2 | AD module hangs (**twice**) | `Get-ADDomain` / `Set-ADDefaultDomainPasswordPolicy` never return (>27 min / >44 min), drag down later calls; pywinrm `read_timeout` does not fire on this host | calls made before ADWS is ready (right after a reboot) wedge the server-side shell; on a low-spec single-core DC the AD module is unreliable overall | **drop the AD module completely**: group and policy operations go through direct ADSI writes (`Put` + `SetInfo`) + a client-side watchdog around every WinRM call (daemon thread, abandon on timeout, `16_ad_extra_fix.py`) |
| 3 | default password policy | the complexity policy rejects the lab password gns3test | domain default: complexity on + minimum length 7 | ADSI direct write `pwdProperties=0, minPwdLength=1` (not Set-ADDefaultDomainPasswordPolicy — avoids #2) |
| 4 | management-channel notes | ping fails / no SSH / PowerShell slow | the firewall blocks ICMP by default; Server Core ships no OpenSSH; 1 vCPU | WinRM 5985 (on by default) is the main channel; probe ports instead of pinging; long tasks run as background scripts with a log |
| 5 | test-script password typo | svc-gns3 login 401 | the test used gns3test instead of svcldap123 | fixed → 200; recorded so nobody reads it as product behavior |

## 3. Same problem, two directories

| Dimension | OpenLDAP | Windows AD | Shared conclusion |
|---|---|---|---|
| **TLS trust chain** | self-signed CA into the VM21 system trust store + a domain name in the uri (dNSName SAN) | self-signed certificate into Root (self-trust) + DC reboot (LSASS rescan) | trust for self-signed certificates is **the biggest shared trap**; the recipe is always three parts: certificate in the store + trusted to a root + reload/restart |
| **attribute visibility** | whitelist model: the {2} attrs decide what bind_dn can read (two traps: member, description) | default allow: everything is readable for authenticated users (no such trap) | opposite permission models. When writing filters for the PR, check the OpenLDAP whitelist first; AD works out of the box |
| **account lockout** | ppolicy overlay + subentry (a four-step recipe with traps) | domain lockout policy (three ADSI attributes) | the behavior shape is identical: **the directory lockout fires before the GNS3 rate limiter** (even the correct password gets 401) and unlocks itself after the window |
| **password policy** | the directory accepts any password (plain text / special chars / Chinese) | default complexity rejects them; relax it first | align the policy with the test passwords **before** creating users, or user creation fails |
| **hangs** | docker pause half-dead → the GNS3 timeout=10 catches it | ADWS wedged → WinRM/client hangs forever | the first one is the system under test behaving well (positive); the second is an environment management problem (negative) — same word "hang", opposite nature |
| **environment odds and ends** | v2 image ports 3890/6360, su-nologin, caseIgnore | no SSH / no ICMP / localized names / slow PS | every environment carries a basket of problems unrelated to LDAP itself; list the environment before touching the protocol layer |

## 4. Shared lessons (reusable rules)

1. **Probe the protocol layer first**: when the directory is unreachable, two commands (`ldapsearch`, `openssl s_client`) split the problem into network / TLS / directory. Both big hunts this round (AD 52, OpenLDAP 32) were located this way.
2. **Self-signed certificate trio**: into the store (with private key) → trusted to a root → reload the service. If any part is missing, the symptom is a handshake-level refusal, not a validation failure.
3. **The permission model's default direction decides the troubleshooting path**: OpenLDAP denies by default (a missing whitelist entry looks like "attribute not present"); AD allows by default (the pain sits in certificate selection and module hangs).
4. **Wrap unreliable channels in a watchdog**: pywinrm's read_timeout did not fire on this host — every remote call gets a daemon-thread timeout that abandons the call. Losing one call is fine; losing the whole session is not.
5. **Test passwords must pass the policy first**: the directory password policy (complexity / length / lockout) is the first invisible gate of any integration test; align it before building the tree.
