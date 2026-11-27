#!/usr/bin/env python3
"""PR #3103 retest — Test 34: login gating (who may log in to GNS3).

GNS3 has no user-whitelist setting. Login passes only when ALL four gates pass:
  1) user entry inside base_dn scope
  2) user_search_filter condition matches
  3) attributes used in the filter are READABLE by bind_dn (OpenLDAP olcAccess
     attribute whitelist — AD has no such pitfall)
  4) account enabled + correct password

This script reproduces the pitfall in both directions (uses ldapmodify from the
test host for directory/ACL changes, controller API for the config flip):

  a) mark alice/dave with description=gns3-allowed, PUT a gated filter
     -> alice/dave STILL 401  (attribute invisible to bind_dn: {2} whitelist)
  b) add `description` to the {2} whitelist
     -> alice/dave 200; bob/frank 401  (gate works both ways)
  c) restore the original filter -> everyone 200 (marks still in place)
  d) restore everything: remove description from {2}, remove user marks

Run from the test host: python3 06_login_gate.py   (needs ldapmodify + network).
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = "http://192.168.101.21"
LDAP = "ldap://192.168.101.31:3890"
BIND_DN = "cn=admin,dc=example,dc=org"
BIND_PW = "admin"
USER_PWD = "gns3test"
GATED_FILTER = "(&(objectClass=person)(uid={username})(description=gns3-allowed))"
ACL_BASE = "olcDatabase={1}mdb,cn=config"
CONFIG_BIND = ("cn=admin,cn=config", "config")
ACL_OLD = ("{2}to attrs=entry,objectClass,cn,sn,givenName,mail,uid,ou,o,dc,member "
           "by self read by users read by * break")
ACL_NEW = ("{2}to attrs=entry,objectClass,cn,sn,givenName,mail,uid,ou,o,dc,member,description "
           "by self read by users read by * break")
TERMINAL = {"uri": "ldap://ldap.example.org:3890", "start_tls": True, "verify_cert": True}


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


def ldapmodify(ldif):
    p = subprocess.run(["ldapmodify", "-x", "-H", LDAP, "-D", BIND_DN, "-w", BIND_PW],
                       input=ldif.encode(), capture_output=True, timeout=30)
    ok = p.returncode == 0
    if not ok:
        print("  ldapmodify FAILED:", p.stderr.decode(errors="replace")[:200])
    return ok


def mark(user, on):
    if on:
        ldif = (f"dn: uid={user},ou=people,ou=gns3,dc=example,dc=org\n"
                "changetype: modify\nadd: description\ndescription: gns3-allowed\n")
    else:
        ldif = (f"dn: uid={user},ou=people,ou=gns3,dc=example,dc=org\n"
                "changetype: modify\ndelete: description\n")
    return ldapmodify(ldif)


def acl(with_description):
    rule = ACL_NEW if with_description else ACL_OLD
    ldif = (f"dn: {ACL_BASE}\nchangetype: modify\ndelete: olcAccess\n"
            f"olcAccess: {ACL_OLD if with_description else ACL_NEW}\n-\n"
            f"add: olcAccess\nolcAccess: {rule}\n")
    p = subprocess.run(["ldapmodify", "-x", "-H", LDAP, "-D", CONFIG_BIND[0], "-w", CONFIG_BIND[1]],
                       input=ldif.encode(), capture_output=True, timeout=30)
    ok = p.returncode == 0
    if not ok:
        print("  ACL ldapmodify FAILED:", p.stderr.decode(errors="replace")[:200])
    return ok


def main():
    _, j = login("admin", "admin")
    admin_token = j["access_token"]
    st, settings = req("GET", "/v3/settings", token=admin_token)
    base_cfg = settings["LDAP"]
    base_cfg["bind_password"] = "svcldap123"
    orig_filter = base_cfg["user_search_filter"]
    print(f"[baseline] filter={orig_filter}")

    def put_filter(desc, flt):
        cfg = dict(base_cfg, user_search_filter=flt)
        st, _ = req("PUT", "/v3/settings", {"LDAP": cfg}, token=admin_token)
        print(f"[PUT filter] {desc}: status={st}")
        time.sleep(5)

    def probe(label):
        res = {u: login(u)[0] for u in ("alice", "dave", "bob", "frank")}
        print(f"[{label}] " + "  ".join(f"{u}={s}" for u, s in res.items()))
        return res

    try:
        # a) marks + gated filter, BEFORE the ACL change -> everyone 401 (the pitfall)
        mark("alice", True); mark("dave", True)
        put_filter("gated (description=gns3-allowed), ACL NOT yet extended", GATED_FILTER)
        probe("a) marked users, pre-ACL: expect alice/dave 401 (attribute unreadable)")

        # b) extend {2} whitelist with description -> gate works both ways
        acl(with_description=True)
        probe("b) after ACL {2} += description: expect alice/dave 200, bob/frank 401")

        # c) restore the original filter -> everyone back in
        put_filter("restore original filter", orig_filter)
        probe("c) original filter restored: expect all 200")
    finally:
        # d) full restoration
        acl(with_description=False)
        mark("alice", False); mark("dave", False)
        st, cfg = req("GET", "/v3/settings", token=admin_token)
        print(f"[restore check] filter={cfg['LDAP']['user_search_filter']}")
        probe("d) after full restoration: expect all 200")


if __name__ == "__main__":
    sys.exit(main())
