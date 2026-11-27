#!/bin/bash
echo '== gns3server journal (LDAP lines, last 30):'
sudo journalctl -u gns3 -n 200 --no-pager 2>/dev/null | grep -iE 'ldap|starttls|tls' | tail -30
echo
echo '== raw ldap3 repro (CERT_REQUIRED then CERT_NONE):'
/home/gns3/.venv/gns3server-venv/bin/python - <<'PYEOF'
import ssl
import ldap3

def attempt(label, validate):
    try:
        tls = ldap3.Tls(validate=validate)
        s = ldap3.Server('ldap://ad.example.org:389', use_ssl=False, tls=tls,
                         connect_timeout=5, get_info=ldap3.NONE)
        c = ldap3.Connection(s, user='CN=svc-gns3,OU=people,OU=gns3,DC=ad,DC=example,DC=org',
                             password='svcldap123', auto_bind=False, auto_referrals=False,
                             check_names=False)
        c.open()
        ok = c.start_tls()
        print(f'[{label}] start_tls={ok} result_desc={c.result.get("description")}')
        if ok:
            c.bind()
            print(f'[{label}] bind={c.bound} desc={c.result.get("description")}')
    except Exception as e:
        print(f'[{label}] EXC {type(e).__name__}: {str(e)[:250]}')

attempt('CERT_REQUIRED', ssl.CERT_REQUIRED)
attempt('CERT_NONE    ', ssl.CERT_NONE)
PYEOF
