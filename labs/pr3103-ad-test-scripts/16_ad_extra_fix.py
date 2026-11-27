#!/usr/bin/env python3
"""Recovery + completion of the AD supplementary matrix (stage-40 T17-T24).

Lessons applied:
- NO AD PowerShell module calls: group ops and lockout policy go through ADSI
  (direct LDAP; the AD-module path wedged twice today).
- every WinRM call runs in a daemon thread with a client-side watchdog; on
  timeout the call is abandoned instead of blocking forever.
- API key deletion is owner-scoped (admin got 403): cleanup uses bob's token.
"""
import json
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, '/tmp/ad-scripts')
from ps import run_ps_code  # noqa: E402

BASE = "http://192.168.101.21"
USER_PWD = "gns3test"
BOB_DN = f"CN=bob,OU=people,OU=gns3,DC=ad,DC=example,DC=org"
GNS3_OU = f"OU=gns3,DC=ad,DC=example,DC=org"
SVC_DN = f"CN=svc-gns3,OU=people,OU=gns3,DC=ad,DC=example,DC=org"

AD_CFG = {
    "enabled": True, "uri": "ldap://ad.example.org:389", "bind_dn": SVC_DN,
    "bind_password": "svcldap123", "base_dn": GNS3_OU,
    "user_search_filter": "(&(objectClass=user)(sAMAccountName={username}))",
    "user_attr_username": "sAMAccountName", "user_attr_email": "mail",
    "user_attr_fullname": "cn", "group_search_base": GNS3_OU,
    "group_search_filter": "(&(objectClass=group)(member={user_dn}))",
    "group_mapping": {"gns3-admins": "Administrators", "gns3-testers": "Testers"},
    "default_group": "Users", "start_tls": True, "verify_cert": True,
    "fallback_to_local": True, "timeout": 10,
}
OPENLDAP_RESTORE = {
    "enabled": True, "uri": "ldap://ldap.example.org:3890",
    "bind_dn": "uid=svc-gns3,ou=people,ou=gns3,dc=example,dc=org",
    "bind_password": "svcldap123", "base_dn": "ou=gns3,dc=example,dc=org",
    "user_search_filter": "(&(objectClass=person)(uid={username}))",
    "user_attr_username": "uid", "user_attr_email": "mail", "user_attr_fullname": "cn",
    "group_search_base": "ou=gns3,dc=example,dc=org",
    "group_search_filter": "(&(objectClass=groupOfNames)(member={user_dn}))",
    "group_mapping": {"gns3-admins": "Administrators", "gns3-testers": "Testers"},
    "default_group": "Users", "start_tls": True, "verify_cert": True,
    "fallback_to_local": True, "timeout": 10,
}


def req(method, path, body=None, token=None, timeout=25):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(r, data=data, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode()), round((time.perf_counter() - t0) * 1000, 1)
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        return e.code, body, round((time.perf_counter() - t0) * 1000, 1)
    except Exception as e:
        return 0, {"error": str(e)}, round((time.perf_counter() - t0) * 1000, 1)


def login(user, pwd=USER_PWD):
    return req("POST", "/v3/access/users/authenticate", {"username": user, "password": pwd})


def members_of(admin_token, name):
    st, groups, _ = req("GET", "/v3/access/groups", token=admin_token)
    gl = groups if isinstance(groups, list) else groups.get("groups", [])
    gid = next((g.get("user_group_id") for g in gl if g["name"] == name), None)
    st, members, _ = req("GET", f"/v3/access/groups/{gid}/members", token=admin_token)
    ml = members if isinstance(members, list) else members.get("members", members.get("users", []))
    return sorted(m.get("username") for m in ml)


def ad(code, label, to=45):
    """Run PS via WinRM in a daemon thread with a client-side watchdog."""
    box = {}

    def worker():
        try:
            r = run_ps_code(code, max(to, 40))
            box['rc'] = r.status_code
            box['out'] = r.std_out.decode(errors='replace').strip()
            box['err'] = r.std_err.decode(errors='replace').strip()
        except Exception as e:
            box['exc'] = f"{type(e).__name__}: {str(e)[:120]}"

    t = threading.Thread(target=worker, daemon=True)
    t0 = time.perf_counter()
    t.start()
    t.join(to)
    if t.is_alive():
        print(f"[AD] {label}: WATCHDOG fired after {to}s -- call abandoned (shell may linger)")
        return False
    ms = round((time.perf_counter() - t0) * 1000)
    rc = box.get('rc')
    print(f"[AD] {label}: rc={rc} {box.get('out', '')[:120]}" + (f" | err={box['err'][-200:]}" if rc != 0 and box.get('err') else ''))
    return rc == 0


GROUP_DN = f"CN=gns3-admins,OU=groups,OU=gns3,DC=ad,DC=example,DC=org"


def group_member(bob_in):
    op = 'Add' if bob_in else 'Remove'
    return ad(f"$g=[ADSI]'LDAP://{GROUP_DN}'; $g.{op}('LDAP://{BOB_DN}'); $g.SetInfo(); '{op}D'", f"{op} bob {'to' if bob_in else 'from'} gns3-admins (ADSI)")


def set_lockout(threshold, dur_s, obs_s):
    code = (f"$d=[ADSI]'LDAP://DC=ad,DC=example,DC=org'; $d.Put('lockoutThreshold',{threshold}); "
            f"$d.Put('lockoutDuration',-{dur_s * 10000000}); $d.Put('lockoutObservationWindow',-{obs_s * 10000000}); "
            f"$d.SetInfo(); 'lockout threshold={threshold}'")
    return ad(code, f"set lockout threshold={threshold} (ADSI)")


def main():
    # ---- 0. cleanup: owner-scoped key deletion (T20 residue) ----
    print("===== cleanup: T20 key (owner-only delete) =====")
    _, j, _ = login("bob")
    bob_token = j["access_token"]
    st, _, _ = req("DELETE", "/v3/access/api-keys/069169c8-8acf-4c7a-ac21-ce8117a53f8a", token=bob_token)
    print(f"[bob deletes his own key] {st} (expect 204 -- delete is owner-scoped, admin got 403)")
    st, _, _ = req("GET", "/v3/access/users", token="gns3_069169c8-8acf-4c7a-ac21-ce8117a53f8a_PLACEHOLDER_NEVER_VALID")
    print("(placeholder probe skipped)")

    # ---- 1. T19 re-verify with delays + ADSI group ops ----
    print("\n===== Test 19 re-verify: refresh x member removal (5s settle) =====")
    st, j, _ = login("bob")
    access, refresh = j["access_token"], j["refresh_token"]
    st, _, _ = req("GET", "/v3/access/users", token=access)
    print(f"[bob access token probe] {st} (expect 200 Administrators)")
    group_member(False)
    time.sleep(5)  # settle delay absent in the first attempt
    st, j, _ = login("bob")
    st, _, _ = req("GET", "/v3/access/users", token=j["access_token"])
    print(f"[fresh login after removal] probe {st} (expect 403 -- removal IS effective for fresh logins)")
    st, j, _ = req("POST", "/v3/access/users/refresh", {"refresh_token": refresh}, timeout=30)
    print(f"[POST refresh (old refresh_token)] {st}")
    new_access = j.get("access_token") if isinstance(j, dict) else None
    if new_access:
        st, _, _ = req("GET", "/v3/access/users", token=new_access)
        print(f"[refreshed token probe] {st} (OpenLDAP behavior: 403; first AD attempt gave 200)")
    group_member(True)
    st, j, _ = login("bob")
    st, _, _ = req("GET", "/v3/access/users", token=j["access_token"])
    print(f"[after re-add] fresh login probe {st} (expect 200)")
    print(f"[Administrators] {members_of(login('admin', 'admin')[1]['access_token'], 'Administrators')}")

    # ---- 2. T23 lockout via ADSI ----
    print("\n===== Test 23: AD native lockout (ADSI set, threshold 3 / 60s) =====")
    set_lockout(3, 60, 60)
    try:
        for i in range(3):
            st, _, _ = login("erin", "wrongpw")
            print(f"[erin wrong #{i + 1}] {st} (expect 401)")
        st, _, ms = login("erin")
        print(f"[erin correct while locked] {st} in {ms}ms (expect 401 -- directory lockout before any 429)")
        time.sleep(66)
        st, _, ms = login("erin")
        print(f"[erin correct after 60s] {st} in {ms}ms (expect 200 auto-unlock)")
    finally:
        set_lockout(0, 1800, 60)
        st, _, _ = login("erin")
        print(f"[erin after policy reset] {st} (expect 200)")

    # ---- 3. T17 outage (netsh block 389/636) ----
    print("\n===== Test 17: directory outage (firewall block) =====")
    st, j, _ = login("alice")
    old_token = j["access_token"]
    ad('netsh advfirewall firewall add rule name="block-ldap-t17" dir=in action=block protocol=TCP localport=389,636; "blocked"', "block 389/636")
    try:
        time.sleep(1)
        st, _, ms = login("admin", "admin")
        print(f"[admin local escape] {st} in {ms}ms (expect 200 fallback)")
        st, _, ms = req("GET", "/v3/access/users", token=old_token)
        print(f"[alice old token during outage] {st} in {ms}ms (expect 403 fail-open)")
        st, _, ms = login("alice")
        print(f"[alice fresh login during outage] {st} in {ms}ms (expect 401)")
    finally:
        ad('netsh advfirewall firewall delete rule name="block-ldap-t17"; "unblocked"', "remove block rule")
    st, _, ms = login("alice")
    print(f"[alice login after recovery] {st} in {ms}ms (expect 200)")

    # ---- 4. T18 rate limiter ----
    print("\n===== Test 18: rate limiter =====")
    t0 = time.perf_counter()
    for i in range(5):
        st, _, _ = login("dave", "wrongpw")
        print(f"[dave wrong #{i + 1}] {st} (expect 401)")
    st, _, _ = login("dave")
    print(f"[dave correct #6, t={time.perf_counter() - t0:.1f}s] {st} (expect 429)")
    time.sleep(25)
    st, _, _ = login("dave")
    print(f"[dave correct in-window, t={time.perf_counter() - t0:.1f}s] {st} (expect 429)")
    time.sleep(40)
    st, _, ms = login("dave")
    print(f"[dave correct after window, t={time.perf_counter() - t0:.1f}s] {st} in {ms}ms (expect 200 unblock)")
    print("\nALL REMAINING SECTIONS DONE")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            _, j, _ = login("admin", "admin")
            admin_token = j["access_token"]
            st, _, _ = req("PUT", "/v3/settings", {"LDAP": OPENLDAP_RESTORE}, token=admin_token)
            print(f"[PUT settings] RESTORE OpenLDAP terminal: status={st}")
            time.sleep(5)
            st, _, _ = login("carol")
            print(f"[restore sanity] carol login: {st} (expect 200)")
            print(f"[restore members] Administrators={members_of(admin_token, 'Administrators')}")
        except Exception as e:
            print(f"[restore] EXC {type(e).__name__}: {str(e)[:200]}")
