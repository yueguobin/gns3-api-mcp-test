# PR #3103 LDAP retest scripts — run order & caveats

Target: LDAP-enabled GNS3 3.1 controller (default `http://192.168.101.21`,
override as argv[1]). All scripts are stdlib-only (`python3 -I script.py`).
Full runbook: `mcp_test_docs/en/stage38_ldap_auth_pr3103_openldap26_test_en.md` §4
(中文: `mcp_test_docs/zh/阶段38_PR3103-LDAP认证与OpenLDAP联测报告.md` §6).

Prerequisites: terminal LDAP config active (`start_tls=True`, `verify_cert=True`,
uri `ldap://ldap.example.org:3890`, mappings `gns3-admins→Administrators`,
`gns3-testers→Testers`); directory reachable from the controller; local admin
`admin/admin`; test users password `gns3test`.

| Order | Script | Covers | Caveats |
|---|---|---|---|
| 1 | `01_no_config_tests.py` | tests 1–5, 11, 12 (logins, memberships, ldap/test, masking) | read-only; safe to re-run |
| 2 | `02_membership_audit.py` | carol login + membership audit | pair with the `ldapmodify` revoke/restore commands in the runbook |
| 3 | `03_config_flips.py` | test 9 TLS variants + test 7 frank flip | mutates `/v3/settings`; `finally` block always restores terminal config |
| 4 | `04_dr_recover_wait.py` | recovery poller after `node_start` | 429 responses during polling = rate limiter (outage failures count), not necessarily still-down |
| 5 | `05_rate_limiter.py` | test 10 rate limiter | run LAST — blocks username `dave` for ~60 s |

DR phase (between 03 and 05): save an alice token, stop the OpenLDAP-1 node
(GNS3 MCP `node_stop` / GUI), run the three probe curls, start the node
(`node_start`), then `04_dr_recover_wait.py`. Exact commands in the runbook.
