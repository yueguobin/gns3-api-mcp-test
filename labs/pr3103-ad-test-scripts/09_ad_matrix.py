#!/usr/bin/env python3
"""PR #3103 -- Windows AD (GNS3-AD / ad.example.org) functional matrix.

Flow: ldap/test probe -> PUT AD config -> login/group matrix -> frank flip ->
disabled-account -> LDAPS variant + IP negative -> restore OpenLDAP config.
Restore is in finally: always puts back the OpenLDAP terminal config.
"""
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, '/tmp/ad-scripts')

BASE = "http://192.168.101.21"
USER_PWD = "gns3test"

AD_ROOT_DN = "DC=ad,DC=example,DC=org"
GNS3_OU = f"OU=gns3,{AD_ROOT_DN}"
SVC_DN = f"CN=svc-gns3,OU=people,OU=gns3,{AD_ROOT_DN}"

AD_CFG = {
    "enabled": True,
    "uri": "ldap://ad.example.org:389",
    "bind_dn": SVC_DN,
    "bind_password": "svcldap123",
    "base_dn": GNS3_OU,
    "user_search_filter": "(&(objectClass=user)(sAMAccountName={username}))",
    "user_attr_username": "sAMAccountName",
    "user_attr_email": "mail",
    "user_attr_fullname": "cn",
    "group_search_base": GNS3_OU,
    "group_search_filter": "(&(objectClass=group)(member={user_dn}))",
    "group_mapping": {"gns3-admins": "Administrators", "gns3-testers": "Testers"},
    "default_group": "Users",
    "start_tls": True,
    "verify_cert": True,
    "fallback_to_local": True,
    "timeout": 10,
}

OPENLDAP_RESTORE = {
    "enabled": True,
    "uri": "ldap://ldap.example.org:3890",
    "bind_dn": "uid=svc-gns3,ou=people,ou=gns3,dc=example,dc=org",
    "bind_password": "svcldap123",
    "base_dn": "ou=gns3,dc=example,dc=org",
    "user_search_filter": "(&(objectClass=person)(uid={username}))",
    "user_attr_username": "uid",
    "user_attr_email": "mail",
    "user_attr_fullname": "cn",
    "group_search_base": "ou=gns3,dc=example,dc=org",
    "group_search_filter": "(&(objectClass=groupOfNames)(member={user_dn}))",
    "group_mapping": {"gns3-admins": "Administrators", "gns3-testers": "Testers"},
    "default_group": "Users",
    "start_tls": True,
    "verify_cert": True,
    "fallback_to_local": True,
    "timeout": 10,
}


def req(method, path, body=None, token=None, timeout=20):
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


def login(user, pwd=USER_PWD):
    return req("POST", "/v3/access/users/authenticate", {"username": user, "password": pwd})


def members_of(admin_token, name):
    st, groups = req("GET", "/v3/access/groups", token=admin_token)
    if st != 200:
        return f"(groups list {st})"
    gl = groups if isinstance(groups, list) else groups.get("groups", [])
    gid = next((g.get("user_group_id") for g in gl if g["name"] == name), None)
    if not gid:
        return "(group missing)"
    st, members = req("GET", f"/v3/access/groups/{gid}/members", token=admin_token)
    ml = members if isinstance(members, list) else members.get("members", members.get("users", []))
    return sorted(m.get("username") for m in ml)


def put_ldap(admin_token, desc, cfg):
    st, _ = req("PUT", "/v3/settings", {"LDAP": cfg}, token=admin_token)
    print(f"[PUT settings] {desc}: status={st}")
    time.sleep(5)
    return st


def ad_ps(code):
    from ps import run_ps_code
    return run_ps_code(code, 60)


def main():
    _, j = login("admin", "admin")
    admin_token = j["access_token"]
    st, before = req("GET", "/v3/settings", token=admin_token)
    print(f"[baseline GET settings] status={st} uri={before['LDAP']['uri']}")

    # 0) ldap/test probe with AD params (no persistence)
    test_body = dict(AD_CFG)
    st, j = req("POST", "/v3/settings/ldap/test", test_body, token=admin_token, timeout=30)
    print(f"[ldap/test AD] status={st} -> {json.dumps(j)[:400]}")

    put_ldap(admin_token, "AD StartTLS+verify", AD_CFG)

    # 1) login matrix
    for u in ("alice", "bob", "carol", "dave", "erin", "frank", "svc-gns3"):
        st, j = login(u)
        print(f"[login {u}] {st} (expect 200)")

    st, j = login("Alice")  # uppercase sAMAccountName
    print(f"[login 'Alice' uppercase] {st} (expect 200, AD sAMAccountName case-insensitive)")

    st, j = login("admin", "admin")
    print(f"[login admin local] {st} (expect 200, fallback_to_local)")

    # 2) negative logins
    st, j = login("bob", "wrongpw")
    print(f"[login bob wrongpw] {st} (expect 401)")
    st, j = login("nobody")
    print(f"[login nonexistent nobody] {st} (expect 401)")
    st, j = login("alice@ad.example.org")
    print(f"[login alice@ad.example.org (mail as username)] {st} (expect 401, attr=sAMAccountName only)")

    # 3) authoritative membership
    print(f"[Administrators] {members_of(admin_token, 'Administrators')} (expect [bob,carol,erin])")
    print(f"[Testers] {members_of(admin_token, 'Testers')} (expect [carol,dave] + historic extras)")
    users = members_of(admin_token, "Users")
    print(f"[Users] {users} (expect alice/frank/svc-gns3 fallback present)")

    # 4) frank superadmin flip
    gm = dict(AD_CFG["group_mapping"])
    gm["gns3-superadmins"] = "Administrators"
    cfg = dict(AD_CFG, group_mapping=gm)
    put_ldap(admin_token, "flip: add gns3-superadmins mapping", cfg)
    st, j = login("frank")
    print(f"  -> frank login {st}; Administrators={members_of(admin_token, 'Administrators')} (expect incl frank)")
    put_ldap(admin_token, "flip back: remove mapping", AD_CFG)
    st, j = login("frank")
    print(f"  -> frank login {st}; Administrators={members_of(admin_token, 'Administrators')} (expect no frank)")

    # 5) AD disabled account
    r = ad_ps("Disable-ADAccount -Identity alice; 'disabled'")
    print(f"[Disable-ADAccount alice] {r.std_out.decode(errors='replace').strip()}")
    st, j = login("alice")
    print(f"[login alice disabled] {st} (expect 401 -- AD refuses bind for disabled account)")
    r = ad_ps("Enable-ADAccount -Identity alice; 'enabled'")
    print(f"[Enable-ADAccount alice] {r.std_out.decode(errors='replace').strip()}")
    st, j = login("alice")
    print(f"[login alice re-enabled] {st} (expect 200)")

    # 6) LDAPS variant + IP negative
    cfg = dict(AD_CFG, uri="ldaps://ad.example.org:636", start_tls=False)
    put_ldap(admin_token, "LDAPS hostname 636 + verify", cfg)
    st, j = login("carol")
    print(f"[login carol LDAPS] {st} (expect 200)")
    cfg = dict(AD_CFG, uri="ldaps://192.168.101.32:636", start_tls=False)
    put_ldap(admin_token, "LDAPS IP (negative)", cfg)
    st, j = login("carol")
    print(f"[login carol LDAPS-IP] {st} (expect 401, ldap3 rejects IP hostname vs dNSName SAN)")
    put_ldap(admin_token, "back to StartTLS AD", AD_CFG)
    st, j = login("carol")
    print(f"[login carol StartTLS] {st} (expect 200)")


if __name__ == "__main__":
    try:
        main()
    finally:
        _, j = login("admin", "admin")
        admin_token = j["access_token"]
        put_ldap(admin_token, "RESTORE OpenLDAP terminal", OPENLDAP_RESTORE)
        st, j = login("carol")
        print(f"[restore sanity] carol login: {st} (expect 200)")
        print(f"[restore sanity] Administrators={members_of(admin_token, 'Administrators')}")
        st, cfg = req("GET", "/v3/settings", token=admin_token)
        L = cfg["LDAP"]
        print(f"[restore verify] uri={L['uri']} start_tls={L['start_tls']} verify_cert={L['verify_cert']} mapping={L['group_mapping']}")
