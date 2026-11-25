# GNS3 PR #3103 LDAP Authentication × OpenLDAP 2.6 Integration Test Report (Stage 38)

| Item | Content |
|---|---|
| Test dates | 2026-11-25 (directory upgraded to 2.6.15, TLS surface tested green); **2026-11-26 full-matrix retest 13/13 green (§3)** |
| Target under test | gns3/gns3-server **PR #3103** (feat/ldap-auth; local branch `merge-ldap-3103`; deployed build reports `3.1.0.dev8` — judge the branch by features, not the version string) + **OpenLDAP-1** GNS3 docker node (`osixia/openldap:2.6.15`, `ldap://ldap.example.org:3890`, IP 192.168.101.31; first-round tests ran on 1.5.0:389, see Finding 3/4) |
| Scope | Full LDAP authentication matrix, 13 items: group mapping / dual-group recalc / membership revocation / role flip / JIT fallback / case normalization / DR fallback / TLS paths / login rate limiter / diagnostic endpoint / password masking / token behavior during directory outage |
| Method | Controller REST API (curl + Bearer token) as primary; directory-side operations via host `ldap*` CLI against :3890; GNS3 MCP `node_stop`/`node_start` for the DR test; server logs collected via SSH (use `grep -a` — logs contain binary bytes) |
| Markers | ✓ pass · ⚠️ pass with caveat · ✗ defect |

## 0. Test Environment

### 0.1 Directory side — OpenLDAP-1 (docker node on the local compute)

- **Image**: `osixia/openldap:2.6.15`. Container IP **192.168.101.31** (virbr2 segment, reachable from the host). v2 image is a breaking upgrade from 1.5.0: ① listens on **3890 (ldap/StartTLS)** and **6360 (LDAPS)** — *not* 389/636; ② TLS disabled by default; ③ entrypoint is an ELF binary (`/usr/sbin/container`), slapd launched as `ldap` (uid 911) with `ldap://:3890 ldaps://:6360 ldapi:///`; ④ persistent volumes: `/var/lib/openldap/openldap-data`, `/etc/openldap/slapd.d`, `/var/lib/openldap/openldap-backups` (declared via GNS3 `GNS3_VOLUMES`).
- **GNS3 wrapper prerequisite**: GNS3's docker `init.sh` runs the image entrypoint via `su $GNS3_USER`, and `GNS3_USER` comes from the image's `Config.User`. The 2.6.x image declares `User=ldap` with shell `/sbin/nologin` → container crash-looped (*"This account is not available"*) until the wrapper was fixed (**upstream PR #3108**). On 1.5.0 (no `Config.User`) this never triggers. ⚠️ If you switch branches or redeploy the controller, re-check the deployed `init.sh` still carries the fix — a container rebuild with an unfixed wrapper reproduces the crash instantly (hit for real during the 11-26 retest).
- **Bootstrap env**: `OPENLDAP_BOOTSTRAP_SUFFIX=dc=example,dc=org`; directory root password `admin` (`cn=admin,dc=example,dc=org`), config root password `config` (`cn=admin,cn=config`).
- **Directory data** (`labs/openldap-gns3-pr-test.ldif`, 15 entries): suffix `dc=example,dc=org`; test tree isolated under `ou=gns3` (`ou=people`, `ou=groups`); 6 test users **alice / bob / carol / dave / erin / frank** (uniform password `gns3test`, `inetOrgPerson` with uid/cn/sn/mail) + service account **uid=svc-gns3** (password `svcldap123`, used as GNS3 `bind_dn`); 4 `groupOfNames` groups: `all-staff`[alice], `gns3-superadmins`[frank], `gns3-admins`[bob,carol,erin], `gns3-testers`[carol,dave].
- **No `memberOf` overlay** → group resolution exercises the PR's directory-search fallback, filter `(&(objectClass=groupOfNames)(member=<userDN>))`.
- **uid matching is caseIgnore** (OpenLDAP default): an uppercase `uid=Alice` entry cannot be created; the case trap is therefore exercised on the login string, not via two DNs.
- **ACL patch (required)**: the v2 image's default ACL `{2}` is an attribute whitelist (`entry,objectClass,cn,sn,givenName,mail,uid,ou,o,dc`) that **lacks `member`** → group resolution silently returns 0 entries (blocked by `{3} to * by * none`). Patch `labs/openldap26-acl-member-read.ldif` appends `member` to `{2}`:
  `ldapmodify -x -H ldap://192.168.101.31:3890 -D "cn=admin,cn=config" -w config -f openldap26-acl-member-read.ldif`
  (Related 1.5.0-era lesson: the stock ACL must also grant `by users read` on searched attributes, otherwise the `bind_dn` binds fine but every search returns `32 No such object`.)
- **TLS material**: self-signed certificate (CN=192.168.101.31; SAN `DNS:localhost,DNS:ldap.example.org,IP:192.168.101.31`; RSA-2048, 10 years) deployed to `/var/lib/openldap/openldap-data/tls/` (persistent volume; chown 911:911, key chmod 600). `olcTLSCertificateFile` / `olcTLSCertificateKeyFile` / `olcTLSCACertificateFile` go on **`dn: cn=config`** (the global entry) — putting them on the frontend DB entry fails with error 65 (object class violation).

### 0.2 Controller side — VM21 (192.168.101.21)

- PR #3103 build on a GNS3 3.1 controller; REST API at `http://192.168.101.21:80`.
- Auth mechanics: `POST /v3/access/users/authenticate` (JSON credentials) → Bearer JWT. **Settings endpoints reject Basic auth — Bearer required.** Local admin `admin`/`admin` works out of the box (RBAC default).
- `PUT /v3/settings` body shape is `{"LDAP": {...}}` (flat LDAP body → 422). **`bind_password` must be re-sent in clear on every PUT** — `GET` returns the masked `**********`. Wait ~5 s after each PUT (settings-reload window, see Finding 2).
- **`get_info=NONE` fix deployed**: without it every login fails on plain OpenLDAP (root cause: `get_info=ALL` + hardcoded AD attributes → ldap3 schema validation rejects `sAMAccountName` etc. → `LDAPAttributeError` on the first user search; reported with full chain in the [first PR comment](https://github.com/GNS3/gns3-server/pull/3103#issuecomment-7151325456); local patch archived as `labs/ldap-3103-getinfo-none.patch`).
- VM21 system trust store: `gns3-lab-ldap.crt` → `/usr/local/share/ca-certificates/` + `update-ca-certificates` (ldap3 with `verify_cert=True` trusts the system CA store).
- `/etc/hosts` on VM21: `192.168.101.31 ldap.example.org` — **required, not cosmetic**: on Python ≥ 3.12 ldap3 2.9.1 falls back to its vendored `match_hostname` backport, which **rejects IP-address hostnames** (see Finding 5). An IP-based `uri` with `verify_cert=True` can never pass, regardless of certificate quality.
- Terminal `[LDAP]` section of `gns3_server.conf` (API-verified):

  ```
  uri               = ldap://ldap.example.org:3890
  start_tls         = True
  verify_cert       = True
  bind_dn           = uid=svc-gns3,ou=people,ou=gns3,dc=example,dc=org
  base_dn           = ou=gns3,dc=example,dc=org   # single base covering ou=people AND ou=groups
  user_search_filter= (&(objectClass=person)(uid={username}))
  user_attr_username= uid
  fallback_to_local = True
  group_mapping     = {"gns3-admins": "Administrators", "gns3-testers": "Testers"}
  ```

- ldap3 2.9.1 (as pinned by the PR). API note: `start_tls` is **not** a `Server()`/`Connection()` kwarg in 2.9.1 — the service calls `connection.open()` → `connection.start_tls()` → `connection.bind()` manually.

### 0.3 Tooling

Host `ldap*` CLI (openldap2 client; URI-only `-H`) against `192.168.101.31:3890`; curl against `192.168.101.21:80` with Bearer tokens; GNS3 MCP `node_stop`/`node_start` to take the directory down/up for DR; authoritative group membership read via `GET /v3/access/groups/{user_group_id}/members` (the list endpoint carries no members; the id key is `user_group_id`).

## 1. Per-item Results

| # | Scenario | Result | Key evidence |
|---|---|---|---|
| 1 | bob/carol/erin login → `gns3-admins` mapped | ✓ | all three 200; authoritative check `GET …/members` → **Administrators=[bob,carol,erin]** exact; log: `Assigned user … group 'Administrators'` |
| 2 | carol in two mapped groups | ✓ | after mapping `gns3-testers`→Testers: **carol ∈ Administrators ∧ carol ∈ Testers**; no Users fallback (fallback only when zero mapped groups — correct) |
| 3 | unmapped member (dave, Testers mapping absent) | ✓ | silently lands in default group Users, no error, no auto-created group; flows back to Testers once the mapping exists |
| 4 | frank (`gns3-superadmins`) unmapped | ✓ | stays in Users, is_superadmin=False (branch dropped `superadmin_groups`; superadmin = Administrators membership) |
| 5 | login string `"Alice"` (uppercase) | ✓ | 200 with `username: "alice"`; log `canonical_username='alice'`; same account updated (casefold, commit 1b641bb49) |
| 6 | membership revocation recalc | ✓ | delete carol's `member` from `gns3-admins` → next login **stripped from Administrators** ([bob,erin]), Testers kept; restore `member` → flows back. "Managed groups recalculated on every login" fully holds |
| 7 | frank role flip (add/remove mapping) | ✓ | add `gns3-superadmins`→Administrators → ∈ Administrators ([bob,carol,erin,frank]); remove → back to Users only. Full closed loop |
| 8 | DR fallback | ✓ | directory stopped → **admin login 200 in 0.27 s** (local admin precedes directory query); alice new login 401 (3.1–10 s, connect-timeout path) → directory restarted → alice 200 (73 ms) |
| 9 | TLS paths (StartTLS 3890 / LDAPS 6360 / verify_cert both / negative) | ✓ | StartTLS+verify_cert=True: carol 200 (CA in system store + hostname URI); verify_cert=False: 200; LDAPS hostname+verify_cert=True: 200; negative LDAPS with IP uri+verify_cert=True → **401** (verification is real; also proves Finding 5); wrong password over TLS → 401 ✓. First round on 1.5.0 was ⚠️ (environment, Finding 3); all green on 2.6.15 |
| 10 | login rate limiter (sliding window 5/60 s) | ✓ | dave: 5×401 → 6th attempt (correct password) **429** → still 429 inside window → **unblocked at exactly t+60 s** (200) |
| 11 | POST /v3/settings/ldap/test | ✓ | flat body (**not** `{"LDAP":…}`-wrapped — wrapped returns 422); `{"status":"success","bind_successful":true,"user_search_successful":true,"users_found":5,"latency_ms":1.7–24.5}`; users_found=5 is the canary search's `size_limit=5` sample cap (ldap.py:544), not a counting bug (tree has 7 uids) |
| 12 | GET /v3/settings password masking | ✓ | `bind_password` returned as `'**********'`, no leak |
| 13 | token validity during directory outage | ✓ | alice's JWT issued before the outage keeps working on `/v3/projects` (200 @7 ms) — local JWT verification **fails open** for already-issued sessions |

## 2. Findings

### Finding 1 — ✗ blocking, PR defect, fixed & reported
On a plain OpenLDAP every LDAP login failed: `_create_server()` used `get_info=ALL` → ldap3 fetches schema → `build_attribute_selection()` validates the hardcoded AD attributes (`sAMAccountName`, …) **ungated by `check_names`** (4e111981c's defense ineffective) → `LDAPAttributeError` on first user search → all 401. Fix: `get_info=NONE` (schema unused elsewhere). Reported with full root-cause chain in the [first PR comment](https://github.com/GNS3/gns3-server/pull/3103#issuecomment-7151325456); local patch `labs/ldap-3103-getinfo-none.patch`.

### Finding 2 — ⚠️ minor, mechanism unresolved
For a few seconds after `PUT /v3/settings` (LDAP mapping changes), `GET /v3/access/groups` intermittently returns a bare `404 {"message":"Not Found"}`; self-heals, retry succeeds, no server-side log, not reproducible on no-op PUTs. Suspected race in the settings-reload/route-rebuild path; the web UI hits this sequence on every save.

### Finding 3 — ✅ resolved by the 2.6.15 upgrade
The first-round directory `osixia/openldap:1.5.0` (slapd 2.4.57 + OpenSSL 1.1.1d, 2019-era) could not complete a TLS handshake with python ssl (always `UNEXPECTED_EOF`, while the openssl CLI connected fine — split behavior reproduced from two clients). The PR's TLS **error paths** were still fully validated in that round (verify rejection, StartTLS failure, handshake failure logs). After the upgrade to 2.6.15 (slapd 2.6.15) the entire TLS row passes (item 9). Conclusion: the ⚠️ was an environment-era problem, not a PR defect. Note 1.5.0→2.6.15 is a breaking migration — see §0.1 for the port/ACL/TLS/wrapper changes that had to be absorbed.

### Finding 4 — GNS3 core defect (not PR-specific), fixed upstream
GNS3's docker wrapper `init.sh` execs the image entrypoint via `su $GNS3_USER` (user from the image's `Config.User`, docker_vm.py:749). Images declaring a nologin/false shell user crash-loop (*"This account is not available"*) — exactly what `osixia/openldap` 2.6.x declares. **Fixed upstream in PR #3108** (commit d20b908f7). Operational caveat: the fix lives in the controller's code tree — after a branch switch or redeploy, verify the deployed `init.sh` still carries it before starting docker nodes (a rebuild with the unfixed script reproduces the crash; encountered for real during the 11-26 retest and resolved by restoring the fix + controller restart).

### Finding 5 — ldap3 library limitation inherited by the PR
Since Python ≥ 3.12 removed `ssl.match_hostname`, ldap3 2.9.1 uses its vendored backport (Python 3.4.3 semantics), which **rejects IP addresses as hostnames** (dNSName SANs only; CN not even consulted when DNS SANs exist). Consequence: `uri` using an IP (e.g. `ldaps://192.168.101.31:6360`) + `verify_cert=True` **always fails**, no matter how correct the certificate (IP SAN present and matching — verified). Workaround: hostname-based `uri` + hosts entry (this test used `ldap.example.org`). Worth a note in the PR docs, or an upstream ldap3 fix.

### Observations (non-defects)
- `users_found=5` in the diagnostic endpoint = `size_limit=5` canary cap (by design).
- `PUT /settings` must explicitly carry the real `bind_password` every time (GET returns the mask); PUT-ing the mask back is untested — always re-sent the true value.
- Failed logins caused by **LDAP connection failures also count toward the rate-limit window** (observed 11-26: during the outage the same username's retries hit 429). Semantically defensible (protects the directory, blocks brute force), but worth knowing while troubleshooting a directory outage.
- Directory data survives container rebuilds (persistent volumes) — post-rebuild membership audit showed zero drift.

## 3. Full-Matrix Retest — 2026-11-26 (post-fix deployment)

The complete 13-item matrix was re-run end-to-end on the 2.6.15 terminal environment (StartTLS + verify_cert=True steady state, both mappings active): **13/13 green**, consistent with the first round. Highlights: revocation strip/restore loop exact ([bob,erin] → [bob,carol,erin]); TLS variants re-verified incl. the IP-uri negative (401); frank flip closed loop; DR timings admin 0.27 s / old token 7 ms / recovery 73 ms; rate limiter unblocked at exactly t+60 s. Full detail in the Chinese report §5 (`mcp_test_docs/zh/阶段38_PR3103-LDAP认证与OpenLDAP联测报告.md`).

## 4. Conclusion

All core claims of PR #3103's LDAP authentication **hold in this OpenLDAP environment (13/13, retested end-to-end, incl. the TLS surface)**: JIT provisioning, group mapping, dual-group membership, revocation recalculation, role flips, case normalization, DR fallback, rate limiting, password masking, the diagnostic endpoint, and StartTLS/LDAPS with `verify_cert` both ways plus a negative case. One blocking compatibility defect (Finding 1) was root-caused, fixed (`get_info=NONE`), verified and reported upstream; the first-round TLS ⚠️ was attributed to the aged 1.5.0 image (Finding 3) and went green after the 2.6.15 migration. By-products: GNS3 docker wrapper su/nologin defect (Finding 4, fixed upstream as #3108) and the ldap3 IP-uri hostname limitation (Finding 5, doc-note suggested). Reproduction requires the environment prerequisites in §0 — most notably the `member` ACL patch, the hostname-based `uri`, CA trust on the controller, and a wrapper-fixed `init.sh`.
