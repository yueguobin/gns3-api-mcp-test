#!/usr/bin/env python3
"""PR #3103 -- Windows AD supplementary matrix (stage-40 Tests 17-24).

17 outage & recovery (firewall block 389/636 -> admin escape / old-token fail-open
                      / fresh login 401 / instant recovery)
18 rate limiter      (dave 5x401 -> 429 -> exact t+60s unblock)
19 refresh x member  (remove bob from gns3-admins -> refresh re-calculates)
20 API key x AD      (key survives account disable; rights converge at next login)
21 bind_dn broken    (svc-gns3 password broken -> all logins 401 fast -> restore)
22 input boundaries  (empty password / special-char password / whitespace-folded
                      username / Chinese username / 2000-char username)
23 AD native lockout (domain lockout threshold 3 -> correct password also 401,
                      auto-unlock 60s; mirror of OpenLDAP ppolicy test)
24 ldap/test variants(bad bind_password -> error; good -> success users_found=5)

Every section restores its own state; the finally block restores the OpenLDAP
baseline config and verifies it. AD-side actions go through WinRM (ps.py).
"""
import json
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, '/tmp/ad-scripts')
from ps import run_ps_code  # noqa: E402

BASE = "http://192.168.101.21"
USER_PWD = "gns3test"
AD_ROOT_DN = "DC=ad,DC=example,DC=org"
GNS3_OU = f"OU=gns3,{AD_ROOT_DN}"
SVC_DN = f"CN=svc-gns3,OU=people,OU=gns3,{AD_ROOT_DN}"

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


def ad(code, label):
    try:
        r = run_ps_code(code, 90)
        out = r.std_out.decode(errors="replace").strip()
        err = r.std_err.decode(errors="replace")
        print(f"[AD] {label}: rc={r.status_code} {out[:150]}")
        if r.status_code != 0 and err.strip():
            print("     stderr:", err[-400:])
        return r.status_code == 0
    except Exception as e:
        print(f"[AD] {label}: EXC {type(e).__name__}: {str(e)[:150]}")
        return False


def put_ldap(admin_token, desc, cfg):
    st, _, _ = req("PUT", "/v3/settings", {"LDAP": cfg}, token=admin_token)
    print(f"[PUT settings] {desc}: status={st}")
    time.sleep(5)


def t21_bind_dn(admin_token):
    print("\n===== Test 21: bind_dn broken (svc-gns3 password) =====")
    ad("Set-ADAccountPassword -Identity svc-gns3 -Reset -NewPassword (ConvertTo-SecureString 'brokenpw1' -AsPlainText -Force); 'broken'", "break svc password")
    st, _, ms = login("alice")
    print(f"[login alice w/ broken bind_dn] {st} in {ms}ms (expect 401 fast)")
    ad("Set-ADAccountPassword -Identity svc-gns3 -Reset -NewPassword (ConvertTo-SecureString 'svcldap123' -AsPlainText -Force); 'restored'", "restore svc password")
    st, _, ms = login("alice")
    print(f"[login alice restored] {st} in {ms}ms (expect 200)")


def t24_ldap_test_variants(admin_token):
    print("\n===== Test 24: ldap/test diagnostic variants =====")
    bad = dict(AD_CFG, bind_password="wrong-bindpw")
    st, j, _ = req("POST", "/v3/settings/ldap/test", bad, token=admin_token, timeout=30)
    print(f"[ldap/test bad bind_pw] {st} -> {json.dumps(j)[:160]}")
    st, j, _ = req("POST", "/v3/settings/ldap/test", AD_CFG, token=admin_token, timeout=30)
    print(f"[ldap/test good] {st} -> {json.dumps(j)[:160]}")


def t22_boundaries(admin_token):
    print("\n===== Test 22: input boundaries on AD =====")
    special = 'Gns3!test#2026&<>"'
    ps = "Set-ADAccountPassword -Identity dave -Reset -NewPassword (ConvertTo-SecureString 'Gns3!test#2026&<>\"' -AsPlainText -Force); 'set'"
    ad(ps, "set dave special password")
    st, _, _ = login("dave", special)
    print(f"[login dave special-char password] {st} (expect 200 via JSON)")
    ad("Set-ADAccountPassword -Identity dave -Reset -NewPassword (ConvertTo-SecureString 'gns3test' -AsPlainText -Force); 'restored'", "restore dave password")
    st, _, _ = login("dave")
    print(f"[login dave restored] {st} (expect 200)")
    st, _, _ = login("alice", "")
    print(f"[login alice empty password] {st} (expect 401)")
    st, _, _ = login(" alice ")
    print(f"[login ' alice ' whitespace-folded] {st} (expect 401 on AD if literal match; OpenLDAP gave 200)")
    st, _, _ = login("张三")
    print(f"[login 张三 nonexistent Chinese] {st} (expect 401)")
    st, _, _ = login("a" * 2000)
    print(f"[login 2000-char username] {st} (expect 401)")


def t19_refresh(admin_token):
    print("\n===== Test 19: refresh x member removal =====")
    st, j, _ = login("bob")
    access, refresh = j["access_token"], j["refresh_token"]
    st, _, _ = req("GET", "/v3/access/users", token=access)
    print(f"[bob access token probe] {st} (expect 200, Administrators)")
    ad("Remove-ADGroupMember -Identity gns3-admins -Members bob -Confirm:$false; 'removed'", "remove bob from gns3-admins")
    st, _, _ = req("GET", "/v3/access/users", token=access)
    print(f"[old access token after removal] {st} (expect 200 fail-open)")
    st, j, _ = req("POST", "/v3/access/users/refresh", {"refresh_token": refresh}, token=None, timeout=30)
    print(f"[POST refresh] {st}")
    new_access = j.get("access_token") if isinstance(j, dict) else None
    if new_access:
        st, _, _ = req("GET", "/v3/access/users", token=new_access)
        print(f"[refreshed token probe] {st} (expect 403, role re-calculated to Users)")
    ad("Add-ADGroupMember -Identity gns3-admins -Members bob; 'readded'", "re-add bob")
    st, j, _ = login("bob")
    st, _, _ = req("GET", "/v3/access/users", token=j["access_token"])
    print(f"[fresh login after re-add] probe {st} (expect 200)")


def t20_api_key(admin_token):
    print("\n===== Test 20: API key x AD disable/revocation =====")
    st, j, _ = login("bob")
    bob_access = j["access_token"]
    st, j, _ = req("POST", "/v3/access/api-keys", {"name": "ad-extra-t20"}, token=bob_access)
    key = j["api_key"]
    kid = j["api_key_id"]
    print(f"[create key as bob] {st} id={kid} prefix={j['key_prefix']}")
    st, _, _ = req("GET", "/v3/access/users", token=key)
    print(f"[key probe] {st} (expect 200, bob=Administrators)")
    ad("Disable-ADAccount -Identity bob; 'disabled'", "disable bob in AD")
    st, _, _ = req("GET", "/v3/access/users", token=key)
    print(f"[key probe w/ bob disabled] {st} (expect 200 -- key path never touches directory)")
    st, _, _ = login("bob")
    print(f"[fresh login bob disabled] {st} (expect 401)")
    ad("Enable-ADAccount -Identity bob; 'enabled'", "re-enable bob")
    st, j, _ = login("bob")
    print(f"[fresh login bob re-enabled] {st} (expect 200; role rewritten Administrators)")
    st, _, _ = req("GET", "/v3/access/users", token=key)
    print(f"[same key probe] {st} (expect 200)")
    ad("Remove-ADGroupMember -Identity gns3-admins -Members bob -Confirm:$false; 'removed'", "remove bob (role revocation)")
    st, j, _ = login("bob")
    print(f"[fresh login after member removal] {st} (expect 200, falls to Users)")
    st, _, _ = req("GET", "/v3/access/users", token=key)
    print(f"[same key probe] {st} (expect 403 -- rights converged at re-login)")
    ad("Add-ADGroupMember -Identity gns3-admins -Members bob; 'readded'", "re-add bob")
    st, j, _ = login("bob")
    st, _, _ = req("GET", "/v3/access/users", token=key)
    print(f"[same key probe after restore] {st} (expect 200)")
    st, _, _ = req("DELETE", f"/v3/access/api-keys/{kid}", token=admin_token)
    print(f"[delete key] {st} (expect 204)")
    st, _, _ = req("GET", "/v3/access/users", token=key)
    print(f"[deleted key probe] {st} (expect 401)")


def t23_lockout(admin_token):
    print("\n===== Test 23: AD native lockout policy (mirror of ppolicy) =====")
    ad("Set-ADDefaultDomainPasswordPolicy -LockoutThreshold 3 -LockoutDuration (New-TimeSpan -Seconds 60) -LockoutObservationWindow (New-TimeSpan -Seconds 60); 'policy set'", "set lockout 3/60s")
    try:
        for i in range(3):
            st, _, _ = login("erin", "wrongpw")
            print(f"[erin wrong #{i + 1}] {st} (expect 401)")
        st, _, ms = login("erin")
        print(f"[erin correct while locked] {st} in {ms}ms (expect 401 -- directory lockout, before any 429)")
        st, _, _ = login("erin", "wrongpw")
        print(f"[erin wrong while locked] {st} (expect 401)")
        time.sleep(66)
        st, _, ms = login("erin")
        print(f"[erin correct after 60s] {st} in {ms}ms (expect 200 auto-unlock)")
    finally:
        ad("Set-ADDefaultDomainPasswordPolicy -LockoutThreshold 0 -LockoutDuration (New-TimeSpan -Minutes 30); 'policy reset'", "reset lockout threshold 0")


def t17_outage(admin_token):
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
        print(f"[alice fresh login during outage] {st} in {ms}ms (expect 401; first try may wait timeout=10)")
        st, _, _ = login("nobody")
        print(f"[unknown user during outage] {st} (expect 401)")
    finally:
        ad('netsh advfirewall firewall delete rule name="block-ldap-t17"; "unblocked"', "remove block rule")
    st, _, ms = login("alice")
    print(f"[alice login after recovery] {st} in {ms}ms (expect 200)")
    st, _, _ = req("GET", "/v3/access/users", token=old_token)
    print(f"[alice old token after recovery] {st} (expect 403, Users role)")


def t18_rate_limiter(admin_token):
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


def main():
    _, j, _ = login("admin", "admin")
    admin_token = j["access_token"]
    st, before, _ = req("GET", "/v3/settings", token=admin_token)
    print(f"[baseline] uri={before['LDAP']['uri']}")
    put_ldap(admin_token, "AD StartTLS+verify (supplementary)", AD_CFG)
    st, _, _ = login("carol")
    print(f"[setup check carol] {st} (expect 200)")

    t21_bind_dn(admin_token)
    t24_ldap_test_variants(admin_token)
    t22_boundaries(admin_token)
    t19_refresh(admin_token)
    t20_api_key(admin_token)
    t23_lockout(admin_token)
    t17_outage(admin_token)
    t18_rate_limiter(admin_token)
    print("\nALL SUPPLEMENTARY SECTIONS DONE")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            _, j, _ = login("admin", "admin")
            admin_token = j["access_token"]
            put_ldap(admin_token, "RESTORE OpenLDAP terminal", OPENLDAP_RESTORE)
            st, _, _ = login("carol")
            print(f"[restore sanity] carol login: {st} (expect 200)")
            print(f"[restore members] Administrators={members_of(admin_token, 'Administrators')}")
        except Exception as e:
            print(f"[restore] EXC {type(e).__name__}: {str(e)[:200]}")
