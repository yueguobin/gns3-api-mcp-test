#!/usr/bin/env python3
"""PR #3103 retest — Phase 1: no-config-change items (tests 1-5, 11, 12).

Runs against the LDAP-enabled controller (VM21). Terminal LDAP config must be
active (StartTLS + verify_cert=True, both group mappings). Uses only stdlib.

Usage: python3 01_no_config_tests.py [BASE_URL]
  BASE_URL defaults to http://192.168.101.21 (controller API, port 80)
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.101.21"
USER_PWD = "gns3test"       # uniform password of alice..frank
ADMIN_PWD = "admin"         # local admin (RBAC default)
BIND_PWD = "svcldap123"     # svc-gns3 service account


def req(method, path, body=None, token=None, timeout=15):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(r, data=data, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def login(user, pwd):
    return req("POST", "/v3/access/users/authenticate", {"username": user, "password": pwd})


print("=" * 60)
print("Phase 1: no-config-change tests (terminal: StartTLS+verify_cert=True)")
print("=" * 60)

# admin token
st, j = login("admin", ADMIN_PWD)
admin_token = j.get("access_token", "")
print(f"[admin auth] status={st} token={'yes' if admin_token else 'NO'}")

# test 5: case normalization
st, j = login("Alice", USER_PWD)
print(f"[test5 'Alice' login] status={st} returned_username={j.get('username')!r} (expect 'alice')")

# test 1: bob/carol/erin -> Administrators
for u in ("bob", "carol", "erin"):
    st, j = login(u, USER_PWD)
    print(f"[test1 {u} login] status={st} (expect 200)")

# test 3: dave -> Testers (mapping configured)
st, j = login("dave", USER_PWD)
print(f"[test3 dave login] status={st}")

# test 4: frank -> Users only (no mapping)
st, j = login("frank", USER_PWD)
print(f"[test4 frank login] status={st}")

# authoritative membership
st, groups = req("GET", "/v3/access/groups", token=admin_token)
gmap = {}
for g in (groups if isinstance(groups, list) else groups.get("groups", [])):
    gmap[g.get("name")] = g.get("user_group_id")
print(f"[groups list] status={st} names={list(gmap)}")

for name in ("Administrators", "Testers"):
    st, members = req("GET", f"/v3/access/groups/{gmap[name]}/members", token=admin_token)
    ml = members if isinstance(members, list) else members.get("members", members.get("users", []))
    print(f"[{name} members] -> {sorted(m.get('username') for m in ml)}")
print("  expect Administrators=[bob,carol,erin]; Testers=[carol,dave]+historic extras")

# test 11: POST /v3/settings/ldap/test (flat body, NOT {"LDAP":...}-wrapped)
st, settings = req("GET", "/v3/settings", token=admin_token)
ldap_cfg = settings.get("LDAP", {})
test_body = dict(ldap_cfg)
test_body["bind_password"] = BIND_PWD  # GET returns masked ********** — re-send real value
st, j = req("POST", "/v3/settings/ldap/test", test_body, token=admin_token)
print(f"[test11 ldap/test] status={st} -> {json.dumps(j)}")
print("  expect success/bind_successful=true/user_search_successful=true; users_found=5 = size_limit canary cap")

# test 12: bind_password masked in GET /settings
masked = ldap_cfg.get("bind_password")
print(f"[test12 password mask] GET bind_password={masked!r} -> {'PASS' if masked == '**********' else 'FAIL'}")
print(f"[config] uri={ldap_cfg.get('uri')} start_tls={ldap_cfg.get('start_tls')} verify_cert={ldap_cfg.get('verify_cert')}")
print(f"[config] group_mapping={ldap_cfg.get('group_mapping')}")
