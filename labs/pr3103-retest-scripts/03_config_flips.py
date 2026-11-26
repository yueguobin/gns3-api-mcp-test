#!/usr/bin/env python3
"""PR #3103 retest — Phase 3: config-flip items (test 9 TLS matrix, test 7 role flip).

Each PUT /v3/settings sends the FULL LDAP config with the real bind_password
(GET masks it as **********), waits 5s for the settings reload, tests, and the
finally-block always restores the terminal config and verifies it.

Variants:
  9a StartTLS + verify_cert=False          -> carol 200
  9b LDAPS hostname + verify_cert=True     -> carol 200
  9c LDAPS IP uri + verify_cert=True       -> carol 401 (ldap3 backport rejects
                                              IP hostnames — negative case)
  7  add gns3-superadmins -> Administrators mapping: frank login -> in group;
     remove mapping: frank login -> Users only

Usage: python3 03_config_flips.py [BASE_URL]
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.101.21"
BIND_PWD = "svcldap123"
TERMINAL = {"uri": "ldap://ldap.example.org:3890", "start_tls": True, "verify_cert": True}


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


def login(user, pwd="gns3test"):
    return req("POST", "/v3/access/users/authenticate", {"username": user, "password": pwd})


def members_of(admin_token, name):
    st, groups = req("GET", "/v3/access/groups", token=admin_token)
    if st != 200:
        return f"(groups list {st})"
    gl = groups if isinstance(groups, list) else groups.get("groups", [])
    gid = next((g.get("user_group_id") for g in gl if g["name"] == name), None)
    st, members = req("GET", f"/v3/access/groups/{gid}/members", token=admin_token)
    ml = members if isinstance(members, list) else members.get("members", members.get("users", []))
    return sorted(m.get("username") for m in ml)


_, j = login("admin", "admin")
admin_token = j["access_token"]

st, settings = req("GET", "/v3/settings", token=admin_token)
base_cfg = settings["LDAP"]
base_cfg["bind_password"] = BIND_PWD  # un-mask


def put_ldap(desc, **overrides):
    cfg = dict(base_cfg)
    cfg.update(overrides)
    st, j = req("PUT", "/v3/settings", {"LDAP": cfg}, token=admin_token)
    print(f"[PUT settings] {desc}: status={st}")
    time.sleep(5)  # settings-reload window (Finding 2: transient /groups 404 possible right after)
    return st


try:
    # test 9a: StartTLS + verify_cert=False
    put_ldap("verify_cert=False (StartTLS)", verify_cert=False)
    st, j = login("carol")
    print(f"  -> carol login: {st} (expect 200)")

    # test 9b: LDAPS hostname + verify_cert=True
    put_ldap("LDAPS ldap.example.org:6360", uri="ldaps://ldap.example.org:6360", start_tls=False, verify_cert=True)
    st, j = login("carol")
    print(f"  -> carol login: {st} (expect 200)")

    # test 9c: LDAPS IP + verify_cert=True (negative)
    put_ldap("LDAPS IP 192.168.101.31:6360 (negative)", uri="ldaps://192.168.101.31:6360", start_tls=False, verify_cert=True)
    st, j = login("carol")
    print(f"  -> carol login: {st} (expect 401, ldap3 IP hostname rejection)")

    # test 7: frank role flip
    gm = dict(base_cfg["group_mapping"])
    gm["gns3-superadmins"] = "Administrators"
    put_ldap("add gns3-superadmins mapping", uri=TERMINAL["uri"], start_tls=True, verify_cert=True, group_mapping=gm)
    st, j = login("frank")
    print(f"  -> frank login: {st}; Administrators={members_of(admin_token, 'Administrators')} (expect includes frank)")

    gm.pop("gns3-superadmins")
    put_ldap("remove gns3-superadmins mapping", group_mapping=gm)
    st, j = login("frank")
    admins = members_of(admin_token, "Administrators")
    users = members_of(admin_token, "Users")
    print(f"  -> frank login: {st}; Administrators={admins} (expect no frank); Users has frank={'frank' in users}")

finally:
    put_ldap("RESTORE terminal", uri=TERMINAL["uri"], start_tls=True, verify_cert=True, group_mapping=base_cfg["group_mapping"])
    st, j = login("carol")
    print(f"[terminal sanity] carol login: {st} (expect 200)")
    st, cfg = req("GET", "/v3/settings", token=admin_token)
    L = cfg["LDAP"]
    print(f"[terminal verify] uri={L['uri']} start_tls={L['start_tls']} verify_cert={L['verify_cert']} mapping={L['group_mapping']}")
