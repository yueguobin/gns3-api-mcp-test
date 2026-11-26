# GNS3 PR 3103 LDAP Authentication — Functional Test Report (Stage 39)

> Chinese version: `mcp_test_docs/zh/阶段39_PR3103-LDAP认证功能测试报告.md` (same tests, same results).
> This report uses simple English (CEFR A2/B1).

| Item | Content |
|---|---|
| Test date | 2026-11-26 |
| System under test | gns3-server **3.1.0.dev8** on VM21 (LDAP authentication, build from PR #3103) together with **OpenLDAP-1** (osixia/openldap:2.6.15, `ldap://ldap.example.org:3890` / `ldaps://:6360`, IP 192.168.101.31) |
| Test scope | **Functional test matrix, 23 items**: login (6) / groups and roles (6) / TLS (4) / outage and recovery (5) / admin and diagnostics (2); **plus 9 extra tests from the same day** (broken bind_dn, input limits, half-dead directory timeout, refresh token × revocation, deleted user, password-policy lockout, service restart — see §5) |
| Test method | **Black-box functional tests**: REST API calls (curl and scripts), LDAP commands from the test host, MCP `node_stop` / `node_start`. This report only describes what the features do. It does not discuss code. |
| Setup | The full configuration is in **§0.2 and §0.3** (all commands included). Test scripts: `labs/pr3103-retest-scripts/`. Config check: §0.4. |
| Result mark | ✓ pass — **all 23 items passed** |

## 0. Test environment and configuration

### 0.1 Environment check (on the test day)

- **Controller**: `curl http://192.168.101.21/v3/version` → `{"controller_host":"127.0.0.1","version":"3.1.0.dev8","local":false}`.
- **Topology**: all 8 nodes are started, including the OpenLDAP-1 docker node.
- **Directory reachable**: the test host can reach 192.168.101.31 on port 3890 and port 6360.
- **Active LDAP settings** (from `GET /v3/settings`): `uri=ldap://ldap.example.org:3890`, `start_tls=True`, `verify_cert=True`, `group_mapping={'gns3-admins': 'Administrators', 'gns3-testers': 'Testers'}`.
- **Test tree**: 6 test users alice/bob/carol/dave/erin/frank (same password `gns3test`), one service account svc-gns3 (the `bind_dn`), 4 groups: all-staff[alice], gns3-superadmins[frank], gns3-admins[bob,carol,erin], gns3-testers[carol,dave].
- **Local account**: admin/admin works (`fallback_to_local=True`).

### 0.2 The OpenLDAP directory node (192.168.101.31)

**Node settings** (GNS3 built-in OpenLDAP appliance v2 template, local compute; read from the node API):

| Item | Value |
|---|---|
| image | `osixia/openldap:2.6.15` |
| ports | 3890 (LDAP) / 6360 (LDAPS) — not the classic 389/636 |
| environment (bootstrap runs only at the first start, on an empty directory) | `OPENLDAP_BOOTSTRAP_ORGANIZATION=Example Inc.`<br>`OPENLDAP_BOOTSTRAP_SUFFIX=dc=example,dc=org`<br>`OPENLDAP_BOOTSTRAP_DATA_ROOT_PASSWORD_HASHED=admin`<br>`OPENLDAP_BOOTSTRAP_CONFIG_ROOT_PASSWORD_HASHED=config` |
| extra volumes (persistent) | `/var/lib/openldap/openldap-data`, `/etc/openldap/slapd.d`, `/var/lib/openldap/openldap-backups` |
| accounts it creates | directory admin `cn=admin,dc=example,dc=org` / `admin`; config admin `cn=admin,cn=config` / `config` |

**Step 1 — Import the test tree** (`labs/openldap-gns3-pr-test.ldif`; `-c` makes it safe to run again):

```bash
ldapadd -c -x -H ldap://192.168.101.31:3890 -D "cn=admin,dc=example,dc=org" -w admin \
        -f labs/openldap-gns3-pr-test.ldif
```

The full LDIF file (the entry data is the same as `labs/openldap-gns3-pr-test.ldif` in this repo; the comments are translated into English):

```ldif
# Directory data for the GNS3 LDAP PR test (gns3-server merge-ldap-3103 branch)
# Target tree: ou=gns3,dc=example,dc=org - kept separate from the old demo tree in the node (ou=people/ou=groups/ou=devices)
# Apply with: ldapadd -x -h 192.168.101.31 -D cn=admin,dc=example,dc=org -w admin -f openldap-gns3-pr-test.ldif
#
# All login users (7) share the same password: gns3test
# Service account svc-gns3 password: svcldap123 (used as bind_dn in gns3_server.conf; needs read rights only)
#
# Group member matrix:
#   all-staff        : alice                (no mapping on purpose -> JIT + default_group fallback)
#   gns3-superadmins : frank                (for the superadmin role add/remove flip test)
#   gns3-admins      : bob, carol, erin     (mapped -> GNS3 Administrators)
#   gns3-testers     : carol, dave          (mapped -> GNS3 Testers; carol is in two groups / managed-group recalc)
#   Alice (capital A): no group             (name-case test case)

# ---- container OUs ----
dn: ou=gns3,dc=example,dc=org
objectClass: organizationalUnit
ou: gns3

dn: ou=people,ou=gns3,dc=example,dc=org
objectClass: organizationalUnit
ou: people

dn: ou=groups,ou=gns3,dc=example,dc=org
objectClass: organizationalUnit
ou: groups

# ---- service account (bind_dn) ----
dn: uid=svc-gns3,ou=people,ou=gns3,dc=example,dc=org
objectClass: inetOrgPerson
uid: svc-gns3
cn: GNS3 Service Account
sn: svc-gns3
userPassword: {SSHA}ZrO9juJXB8yVCfROEy1DjMjVi1IDe3pe

# ---- users ----
dn: uid=alice,ou=people,ou=gns3,dc=example,dc=org
objectClass: inetOrgPerson
uid: alice
cn: Alice Newleaf
sn: Newleaf
mail: alice@example.org
userPassword: {SSHA}Px3LFp1dmanIQSpzr4sUEaDuq/GC7+fl

dn: uid=Alice,ou=people,ou=gns3,dc=example,dc=org
objectClass: inetOrgPerson
uid: Alice
cn: Alice Upper
sn: Upper
mail: alice.upper@example.org
userPassword: {SSHA}Px3LFp1dmanIQSpzr4sUEaDuq/GC7+fl

dn: uid=bob,ou=people,ou=gns3,dc=example,dc=org
objectClass: inetOrgPerson
uid: bob
cn: Bob Admin
sn: Admin
mail: bob@example.org
userPassword: {SSHA}Px3LFp1dmanIQSpzr4sUEaDuq/GC7+fl

dn: uid=carol,ou=people,ou=gns3,dc=example,dc=org
objectClass: inetOrgPerson
uid: carol
cn: Carol Multi
sn: Multi
mail: carol@example.org
userPassword: {SSHA}Px3LFp1dmanIQSpzr4sUEaDuq/GC7+fl

dn: uid=dave,ou=people,ou=gns3,dc=example,dc=org
objectClass: inetOrgPerson
uid: dave
cn: Dave Tester
sn: Tester
mail: dave@example.org
userPassword: {SSHA}Px3LFp1dmanIQSpzr4sUEaDuq/GC7+fl

dn: uid=erin,ou=people,ou=gns3,dc=example,dc=org
objectClass: inetOrgPerson
uid: erin
cn: Erin Local
sn: Local
mail: erin@example.org
userPassword: {SSHA}Px3LFp1dmanIQSpzr4sUEaDuq/GC7+fl

dn: uid=frank,ou=people,ou=gns3,dc=example,dc=org
objectClass: inetOrgPerson
uid: frank
cn: Frank Super
sn: Super
mail: frank@example.org
userPassword: {SSHA}Px3LFp1dmanIQSpzr4sUEaDuq/GC7+fl

# ---- groups (groupOfNames, matches the default group_search_filter) ----
dn: cn=all-staff,ou=groups,ou=gns3,dc=example,dc=org
objectClass: groupOfNames
cn: all-staff
member: uid=alice,ou=people,ou=gns3,dc=example,dc=org

dn: cn=gns3-superadmins,ou=groups,ou=gns3,dc=example,dc=org
objectClass: groupOfNames
cn: gns3-superadmins
member: uid=frank,ou=people,ou=gns3,dc=example,dc=org

dn: cn=gns3-admins,ou=groups,ou=gns3,dc=example,dc=org
objectClass: groupOfNames
cn: gns3-admins
member: uid=bob,ou=people,ou=gns3,dc=example,dc=org
member: uid=carol,ou=people,ou=gns3,dc=example,dc=org
member: uid=erin,ou=people,ou=gns3,dc=example,dc=org

dn: cn=gns3-testers,ou=groups,ou=gns3,dc=example,dc=org
objectClass: groupOfNames
cn: gns3-testers
member: uid=carol,ou=people,ou=gns3,dc=example,dc=org
member: uid=dave,ou=people,ou=gns3,dc=example,dc=org
```

Tree layout: suffix `dc=example,dc=org`. The test tree sits under `ou=gns3`. It has `ou=people` (test users + svc-gns3, `inetOrgPerson` with uid/cn/sn/mail) and `ou=groups` (4 `groupOfNames` groups: all-staff[alice], gns3-superadmins[frank], gns3-admins[bob,carol,erin], gns3-testers[carol,dave]).

Import behavior: the file defines 15 entries. The entry `uid=Alice` (capital A) is **not created**. The directory treats uid values as case-insensitive. It answers "Already exists", because `uid=alice` (small a) already exists. This is normal directory behavior. So 14 entries are stored, and `ou=people` holds 7 uid entries (6 users + svc-gns3). This matches all results in this report. The capital-letter case is tested over the login name "Alice" (see test 5).

**Step 2 — ACL patch** (needed; the default `{2}` ACL of the v2 image is an attribute allow-list, and it has no `member` rule. Group search filters on `member`, so the patch must add it. Patch file: `labs/openldap26-acl-member-read.ldif`):

```bash
ldapmodify -x -H ldap://192.168.101.31:3890 -D "cn=admin,cn=config" -w config \
           -f labs/openldap26-acl-member-read.ldif
# Check: the olcAccess {2} rule of olcDatabase={1}mdb must contain member.
# (olcAccess lives on the {1}mdb entry, not on the global cn=config entry.)
```

**Step 3 — TLS** (self-signed certificate, SAN covers the domain name and the IP. The certificate files live in the persistent volume. The olcTLS* attributes go on the global `cn=config` entry. Config file: `labs/openldap26-tls-config.ldif`):

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -keyout server.key -out server.crt -subj "/CN=192.168.101.31" \
  -addext "subjectAltName=DNS:localhost,DNS:ldap.example.org,IP:192.168.101.31"

docker exec GNS3.OpenLDAP-1.<project-id> mkdir -p /var/lib/openldap/openldap-data/tls
docker cp server.crt GNS3.OpenLDAP-1.<project-id>:/var/lib/openldap/openldap-data/tls/
docker cp server.key GNS3.OpenLDAP-1.<project-id>:/var/lib/openldap/openldap-data/tls/
docker exec GNS3.OpenLDAP-1.<project-id> sh -c \
  'chown 911:911 /var/lib/openldap/openldap-data/tls/*; chmod 600 /var/lib/openldap/openldap-data/tls/server.key'

ldapmodify -x -H ldap://192.168.101.31:3890 -D "cn=admin,cn=config" -w config \
           -f labs/openldap26-tls-config.ldif
```

Two rules for this step: the olcTLS* attributes must go on the global `cn=config` entry (on the frontend entry you get error 65). If the attributes already exist, change `add:` to `replace:` (a second `add` gives error 20).

### 0.3 Controller side (VM21, 192.168.101.21)

```bash
# Name resolution (the certificate SAN and the TLS name check need the URI to use the domain name, not the IP)
echo "192.168.101.31 ldap.example.org" >> /etc/hosts

# Trust the lab CA (verify_cert=True uses the system trust store)
scp server.crt gns3@192.168.101.21:/tmp/gns3-lab-ldap.crt
ssh gns3@192.168.101.21 \
  'sudo cp /tmp/gns3-lab-ldap.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates'
```

The `[LDAP]` section of `/opt/gns3/server/gns3_server.conf` (final state, all 15 settings):

```ini
[LDAP]
enabled = True
uri = ldap://ldap.example.org:3890
bind_dn = uid=svc-gns3,ou=people,ou=gns3,dc=example,dc=org
bind_password = svcldap123
base_dn = ou=gns3,dc=example,dc=org
user_search_filter = (&(objectClass=person)(uid={username}))
user_attr_username = uid
user_attr_email = mail
user_attr_fullname = cn
group_search_base = ou=gns3,dc=example,dc=org
group_search_filter = (&(objectClass=groupOfNames)(member={user_dn}))
group_mapping = {"gns3-admins": "Administrators", "gns3-testers": "Testers"}
default_group = Users
start_tls = True
verify_cert = True
fallback_to_local = True
timeout = 10
```

Deployment check: in the venv, `gns3server/services/ldap.py` line 294 says `get_info=NONE` (this comes with the PR head build).

Prerequisite for docker nodes: the init.sh file that the controller injects must have the drop-privileges fallback — `grep -c SU_SHELL_ARG ~/.local/share/GNS3/docker/init.sh` must give 1 or more (we have 4; without this fallback, a 2.6.x image that declares a non-root user cannot start).

### 0.4 Config vs. running system (checked item by item on 2026-11-26)

| Config item | Where it is defined | How we checked | Match |
|---|---|---|---|
| image / ports / 4 environment vars / 3 volumes | §0.2 node settings | node API properties, word by word | ✓ |
| test tree size | §0.2 step 1 | bind as svc-gns3 (the real controller bind_dn) and search: people=7, groups=4 | ✓ |
| ACL {2} allow-list has member | §0.2 step 2 | read olcAccess of `olcDatabase={1}mdb` | ✓ |
| TLS certificate files | §0.2 step 3 | read in the container volume: server.crt 1192 B / server.key 1704 B / owner ldap(911) / key mode 600 | ✓ |
| olcTLS* attributes | §0.2 step 3 | base search on the config DB; paths match §0.2 | ✓ |
| VM21 hosts | §0.3 | read `/etc/hosts`: `192.168.101.31 ldap.example.org` | ✓ |
| VM21 CA | §0.3 | `gns3-lab-ldap.crt` in `/usr/local/share/ca-certificates/`; `gns3-lab-ldap.pem` entry in `/etc/ssl/certs` | ✓ |
| [LDAP] section, 15 settings | §0.3 | read the file, line by line (incl. the real bind_password) | ✓ |
| deployment get_info | §0.3 | ldap.py line 294: `get_info=NONE` | ✓ |
| TLS really in use | §0.3 | tests 13–16 in this report all behave as expected | ✓ |
| init.sh prerequisite | §0.3 | injected copy SU_SHELL_ARG=4; source tree copy =4 | ✓ |

Result: the configuration in §0.2/§0.3 and the running system are the same, item by item. You can rebuild the environment with the commands above. Note: the old copy in the controller source tree under `build/lib/` does not have the init.sh fallback (the running system does not use that folder; clean it before you build a wheel — same note as stage 38 §6).

## 1. Test matrix and results

| Group | Test | Scenario | Result | What we saw |
|---|---|---|---|---|
| A login | Test 1 | Normal LDAP login (alice) | ✓ | 200; answer has `access_token` / `refresh_token` (bearer, expires_in=86400 s) |
| A login | Test 2 | All test users log in | ✓ | bob/carol/dave/erin/frank all 200 |
| A login | Test 3 | Wrong password is rejected | ✓ | bob + wrong password → 401 |
| A login | Test 4 | Unknown user is rejected | ✓ | nosuchuser → 401 |
| A login | Test 5 | Name case is normalized | ✓ | login name `Alice` → 200, answer shows `username: "alice"` (same account) |
| A login | Test 6 | Local account works next to LDAP | ✓ | admin/admin local login 200 |
| B groups | Test 7 | Group mapping gives roles | ✓ | bob/carol/erin (gns3-admins) → Administrators=[bob,carol,erin], checked in the group API |
| B groups | Test 8 | User in two groups | ✓ | carol is in Administrators and in Testers |
| B groups | Test 9 | Group with no mapping falls back | ✓ | alice (all-staff, no mapping) lands in Users; Users list contains alice; her token gets 403 on an admin endpoint (login OK, no admin rights) |
| B groups | Test 10 | Role removed when member is removed | ✓ | ldapmodify removes carol from gns3-admins → next login Administrators=[bob,erin]; Testers keeps carol |
| B groups | Test 11 | Role comes back when member is added | ✓ | member added again → Administrators=[bob,carol,erin] |
| B groups | Test 12 | Superadmin mapping on/off | ✓ | mapping added → frank joins Administrators; mapping removed → frank back in Users |
| C TLS | Test 13 | StartTLS + verify_cert=True (normal state) | ✓ | carol login 200 |
| C TLS | Test 14 | verify_cert=False | ✓ | carol login 200 |
| C TLS | Test 15 | LDAPS 6360 (domain name URI) | ✓ | carol login 200 |
| C TLS | Test 16 | Certificate check negative case (IP URI) | ✓ | LDAPS with IP URI + verify_cert=True → 401 (the check rejects the connection) |
| D outage | Test 17 | Local login when the directory is down | ✓ | `node_stop` on the directory → admin login **200 / 0.27 s** |
| D outage | Test 18 | Old token while the directory is down | ✓ | alice old token on an endpoint → **403 / 4.6 ms** (login still valid; normal RBAC answer) |
| D outage | Test 19 | New login while the directory is down | ✓ | alice new login → 401 (later requests take about 1 s; the first request waits longer, see §3 note 1) |
| D outage | Test 20 | Directory comes back | ✓ | `node_start` → alice login **200 / t+0.1 s** (at once) |
| D outage | Test 21 | Login rate limit and unblock | ✓ | dave: 5 wrong passwords → 401; 6th try with the right password → **429**; stays 429; **exactly at t+60 s → 200** |
| E admin | Test 22 | bind_password is masked | ✓ | `GET /v3/settings` shows `'**********'` — no leak |
| E admin | Test 23 | ldap/test endpoint | ✓ | `{"status":"success","bind_successful":true,"user_search_successful":true,"users_found":5,"latency_ms":17.05}` |

## 2. Steps and outputs

### 2.1 Login tests (tests 1–6)

Login endpoint: `POST /v3/access/users/authenticate`, JSON body `{"username":..., "password":...}`.

```bash
# alice login (test 1)
curl -X POST http://192.168.101.21/v3/access/users/authenticate \
  -H 'Content-Type: application/json' -d '{"username":"alice","password":"gns3test"}'
# → 200; answer fields: access_token / token_type=bearer / expires_in=86400 / refresh_token / refresh_expires_in / username

# negative cases (tests 3/4)
curl -X POST .../authenticate -d '{"username":"bob","password":"wrongpass"}'       # → 401
curl -X POST .../authenticate -d '{"username":"nosuchuser","password":"whatever"}' # → 401

# name case + all users (tests 2/5, labs/pr3103-retest-scripts/01_no_config_tests.py)
python3 -I labs/pr3103-retest-scripts/01_no_config_tests.py
```

Script output (short version):

```text
[admin auth] status=200 token=yes
[test5 'Alice' login] status=200 returned_username='alice'
[test1 bob login] status=200   [test1 carol login] status=200   [test1 erin login] status=200
[test3 dave login] status=200  [test4 frank login] status=200
```

Check that the alice token works (Users role shape):

```bash
curl -o /dev/null -w "%{http_code}" http://192.168.101.21/v3/access/users \
  -H "Authorization: Bearer $ALICE_TOKEN"   # → 403 (login OK, RBAC says no)
```

### 2.2 Group tests (tests 7–12)

How to check group members: login as admin → `GET /v3/access/groups` gives each group's `user_group_id` → `GET /v3/access/groups/{id}/members`.

```text
Administrators -> ['bob', 'carol', 'erin']        # tests 7/8, exact
Testers        -> ['carol', 'dave', 'student-10'] # carol is in two groups
```

Remove and add a member (tests 10/11; directory side, then audit again):

```bash
# remove carol from gns3-admins
printf 'dn: cn=gns3-admins,ou=groups,ou=gns3,dc=example,dc=org\nchangetype: modify\ndelete: member\nmember: uid=carol,ou=people,ou=gns3,dc=example,dc=org\n' \
  | ldapmodify -x -H ldap://192.168.101.31:3890 -D "cn=admin,dc=example,dc=org" -w admin
python3 -I labs/pr3103-retest-scripts/02_membership_audit.py
# seen: [carol login] 200; Administrators -> ['bob','erin']; Testers -> ['carol','dave',...] (kept)

# same DN with add: member to bring her back, then audit again
printf 'dn: cn=gns3-admins,ou=groups,ou=gns3,dc=example,dc=org\nchangetype: modify\nadd: member\nmember: uid=carol,ou=people,ou=gns3,dc=example,dc=org\n' \
  | ldapmodify -x -H ldap://192.168.101.31:3890 -D "cn=admin,dc=example,dc=org" -w admin
# seen: Administrators -> ['bob','carol','erin'] (back)
```

Superadmin flip (test 12, `labs/pr3103-retest-scripts/03_config_flips.py`; the script puts the config back in its `finally` block):

```text
[PUT settings] add gns3-superadmins mapping: status=200
  -> frank login: 200; Administrators=['bob', 'carol', 'erin', 'frank']
[PUT settings] remove gns3-superadmins mapping: status=200
  -> frank login: 200; Administrators=['bob', 'carol', 'erin']; Users has frank=True
[PUT settings] RESTORE terminal: status=200
[terminal verify] uri=ldap://ldap.example.org:3890 start_tls=True verify_cert=True
                  mapping={'gns3-admins': 'Administrators', 'gns3-testers': 'Testers'}
```

Test 9 check (members of Users):

```bash
# admin token → GET /v3/access/groups/4a22b2ce-.../members
# members seen: alice, frank, student-01 … student-10
```

alice (no mapped group) is in Users ✓; frank (after the mapping was removed) is in Users ✓.

### 2.3 TLS tests (tests 13–16)

`03_config_flips.py` puts one config variant after another and tests a carol login each time (`PUT /v3/settings` needs a Bearer token, body shape `{"LDAP": {...}}`, and must send the real bind_password again; wait about 5 s after each PUT):

```text
[PUT settings] verify_cert=False (StartTLS): status=200   -> carol login: 200
[PUT settings] LDAPS ldap.example.org:6360: status=200    -> carol login: 200
[PUT settings] LDAPS IP 192.168.101.31:6360: status=200   -> carol login: 401 (negative: the name check rejects the IP connection)
[PUT settings] RESTORE terminal: status=200
[terminal sanity] carol login: 200
```

### 2.4 Outage and recovery tests (tests 17–20)

```bash
# 1) save a valid alice token (login while the directory is up)
# 2) stop the OpenLDAP-1 node with MCP node_stop
# 3) three probes:
T=$(cat alice_token.txt)
curl -w "...%{http_code} %{time_total}s" -X POST .../authenticate -d '{"username":"admin","password":"admin"}'
# → 200  0.267s (test 17: local login works)
curl -w "...%{http_code} %{time_total}s" http://192.168.101.21/v3/access/users -H "Authorization: Bearer $T"
# → 403  0.005s (test 18: old token still valid)
curl -w "...%{http_code} %{time_total}s" -X POST .../authenticate -d '{"username":"alice","password":"gns3test"}'
# → first try: no answer for 10 s (client timeout); second try → 401  1.051s (test 19)
# 4) start the node again with MCP node_start, then:
python3 -I labs/pr3103-retest-scripts/04_dr_recover_wait.py
# → attempt 1 (t+0.1s): status=200  <- directory back (test 20)
```

### 2.5 Rate limit and diagnostics (tests 21–23)

```bash
python3 -I labs/pr3103-retest-scripts/05_rate_limiter.py
# seen (dave):
phase 1: five wrong passwords  -> [401, 401, 401, 401, 401]
phase 2: 6th attempt CORRECT password -> 429
phase 3: still inside the window, correct password again -> 429
phase 4: poll -> t+55s 429 ... t+60s 200 UNBLOCKED

# diagnostics endpoint (test 23; flat body, not wrapped in {"LDAP":…}):
curl -X POST http://192.168.101.21/v3/settings/ldap/test -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"uri":"ldap://ldap.example.org:3890","bind_dn":"uid=svc-gns3,ou=people,ou=gns3,dc=example,dc=org", ...}'
# → {"status":"success","bind_successful":true,"user_search_successful":true,"users_found":5,"latency_ms":17.05}

# mask (test 22): GET /v3/settings → bind_password = '**********' (PASS)
```

> The rate limit test blocks the test username for 60 s. Run it last.

## 3. Observations (simple facts, no code talk)

1. **First login request when the directory goes down**: the first login request after the outage does not answer at once (in our test, the client gave up after 10 s). The next requests fail fast with 401 (about 1 s). The result is the same: a new LDAP login never works while the directory is down.
2. **users_found=5**: the ldap/test endpoint reports 5 entries. The test tree holds 7 uid entries. 5 is the sample size of this endpoint, not a full count of the directory.
3. **student accounts**: the Testers group contains student-10; the Users group contains student-01…student-10. These accounts were in the lab before this test round. They do not change any result.

## 4. Conclusion

**All 23 functional tests passed.**

- Login works. Wrong passwords and unknown users are rejected (401). Name case is normalized (`Alice` → `alice`). The local admin account works next to LDAP.
- Group mapping gives, removes, and gives back roles correctly. A group with no mapping falls back to Users.
- TLS works in all three modes (StartTLS, LDAPS, verify on/off). The certificate check rejects a connection with a wrong name (IP URI → 401).
- If the directory is down: the local admin can still log in (0.27 s), old tokens stay valid (403, 4.6 ms), new LDAP logins fail (401). After the directory is back, login works at once (t+0.1 s).
- The rate limit blocks a username after 5 failed tries, keeps it blocked for the 60-second window, and frees it exactly at t+60 s.
- The password is masked in the settings. The diagnostics endpoint works.

After the tests, the config stays in its normal state: StartTLS + verify_cert=True + the two group mappings. No change was left behind in the environment.

## 5. Extra tests (same day, 9 more scenarios)

We also tested 9 more common scenarios. The test numbers continue from 24 to 32.

### 5.1 Results table

| Group | Test | Scenario | Result | What we saw |
|---|---|---|---|---|
| F service bind | Test 24 | The bind_dn password is wrong (global failure) | ✓ | We broke the svc-gns3 password on purpose → **all LDAP logins return 401** (fast, about 0.03 s, no error leak). After we restored the old hash → 200 at once |
| G input limits | Test 25 | Empty password | ✓ | 401 (no "empty password = anonymous bind" hole) |
| G input limits | Test 26 | Password with special characters | ✓ | dave's password set to `Gns3!测 试#2026&<>"'` (Chinese, spaces, quotes, symbols) → login **200**; after restore, the normal password works again |
| G input limits | Test 27 | Login name limits | ✓ | Spaces around the name `" alice "` → **200 and normalized to alice** (LDAP caseIgnore semantics ignore leading/trailing spaces; same account); mail as login name → 401; 2000-character name → 401 (fast); unknown Chinese name → 401 |
| H half-dead directory | Test 28 | Port open but service frozen (`docker pause`) | ✓ | Login waits **exactly the configured timeout=10** (we saw 10.02 s) and then returns 401; after `unpause` → 200 in 0.07 s |
| I sessions | Test 29 | refresh token × revocation | ✓ | See §5.3: the old access token stays valid (200, fail-open); **a refresh re-reads the directory** — the refreshed token gets 403 at once. The fail-open window ends at refresh time |
| I sessions | Test 30 | User deleted from the directory, old token | ✓ | We made uid=temp-ghost, logged in (200), deleted the entry → the old token still answers 403 (login valid, not 401); a new login gives 401 |
| J directory policy | Test 31 | Password-policy lockout (3 wrong tries lock for 60 s) | ✓ | See §5.3: after 3 wrong passwords, **even the correct password is rejected (401)** — directory-side lockout, different from the 429 of the rate limit; after 60 s it unlocks itself (200) |
| K service life cycle | Test 32 | Old JWT after a server restart | ✓ | After `systemctl restart gns3`, the old token still answers **403 (not 401)** — the login stays valid, the signing key survives the restart; a new login gives 200 |

Result: **all 9 extra tests passed.**

### 5.2 How we ran it (short)

```bash
# Test 24: replace the svc-gns3 userPassword twice (break it, then restore the original SSHA hash)
# Tests 25/27: boundary JSON bodies at the authenticate endpoint (empty password / " alice " / carol@example.org / 2000 chars / Chinese name)

# Test 26: LDIF value in base64 (userPassword:: <b64>) to avoid escaping; then restore the original SSHA string

# Test 28: docker pause GNS3.OpenLDAP-1.<project-id> → login probe → docker unpause → test again

# Test 30: ldapadd uid=temp-ghost (plain-text password gns3test also works) → login and save token
#         → ldapdelete uid=temp-ghost → probe old token + new login

# Test 32: save an alice token → ssh VM21 'sudo systemctl restart gns3' → wait for the service
#         → probe old token + new login
```

### 5.3 Two behaviors worth noting

**Test 29 refresh × revocation** (full order):

```text
1) carol logs in (200); we save access_token + refresh_token
2) before the change, the access token on /v3/access/users → 200 (Administrators role)
3) we remove carol from gns3-admins and gns3-testers in the directory
4) the old access token → 200 (fail-open: an issued token does not re-check the directory)
5) a fresh login → falls back to Users; its token gets 403
6) POST /v3/access/users/refresh {"refresh_token":…} → 200, new access token
   → the new token gets 403 (the refresh re-calculates roles from the directory!)
7) member restored → fresh login 200, probe 200
```

Meaning: an issued access token stays valid until it expires (fail-open), but **every refresh re-calculates**. The role catches up at refresh time, not only at login.

**Test 31 password-policy lockout** (how to set it up in this environment: the image already ships the `cn={4}ppolicy` schema, no import needed; load module `ppolicy.so`, add `olcOverlay=ppolicy` on `{1}mdb`, create a policy entry (`organizationalRole` structural class + `pwdPolicy` auxiliary class, pwdLockout=TRUE / pwdMaxFailure=3 / pwdLockoutDuration=60), and attach it to the user with `pwdPolicySubentry`):

```text
3 wrong passwords → 401 × 3
4th try = correct password → 401 (directory-side lockout; the rate limit needs 5 tries, so this 401 comes before any 429)
wait 61 s (pwdLockoutDuration=60) → correct password → 200 (self-unlock; a successful bind resets the failure count)
```

Meaning: the directory password policy and the GNS3 rate limit are **two independent protection layers** — the lockout makes even the correct password fail (401), and it triggers before the rate limit. It unlocks itself, no admin work needed.

### 5.4 What stayed in the environment

- Tests 24/26: passwords restored to the original hashes and re-checked. Test 30: the temp entry is deleted. Test 29: group members restored (Administrators=[bob,carol,erin] verified).
- Test 31 cleanup: no overlay, no policy entry, no subentry left. The `olcModuleLoad: {2}ppolicy.so` line stays (OpenLDAP does not allow removing a module load at runtime, error 80; without an overlay it does nothing; the `cn={4}ppolicy` schema comes with the image).
- Test 32: the service was restarted and runs normally (/v3/version answers).
