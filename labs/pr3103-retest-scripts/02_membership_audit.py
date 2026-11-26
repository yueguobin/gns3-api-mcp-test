#!/usr/bin/env python3
"""PR #3103 retest — Phase 2 helper: carol login + authoritative membership audit.

Used before/after the directory-side revocation (ldapmodify delete/add member on
cn=gns3-admins) to prove managed groups are recalculated on every login.

Usage: python3 02_membership_audit.py [BASE_URL]
"""
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.101.21"


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


_, j = login("admin", "admin")
admin_token = j["access_token"]

st, j = login("carol")
print(f"[carol login] status={st}")

st, groups = req("GET", "/v3/access/groups", token=admin_token)
gmap = {g["name"]: g.get("user_group_id") for g in (groups if isinstance(groups, list) else groups.get("groups", []))}
for name in ("Administrators", "Testers"):
    st, members = req("GET", f"/v3/access/groups/{gmap[name]}/members", token=admin_token)
    ml = members if isinstance(members, list) else members.get("members", members.get("users", []))
    print(f"[{name}] -> {sorted(m.get('username') for m in ml)}")
