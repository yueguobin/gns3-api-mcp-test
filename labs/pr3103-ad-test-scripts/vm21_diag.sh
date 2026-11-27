#!/bin/bash
echo '== getent hosts ad.example.org:'
getent hosts ad.example.org
echo '== tcp 389 by name:'
timeout 3 bash -c 'cat < /dev/null > /dev/tcp/ad.example.org/389' && echo OPEN || echo FAIL
echo '== tcp 389 by ip:'
timeout 3 bash -c 'cat < /dev/null > /dev/tcp/192.168.101.32/389' && echo OPEN || echo FAIL
echo '== raw ldap3 (same venv as gns3server), start_tls + verify:'
/home/gns3/.venv/gns3server-venv/bin/python - <<'PYEOF'
import ldap3
try:
    s = ldap3.Server('ldap://ad.example.org:389', get_info=ldap3.NONE, connect_timeout=5)
    c = ldap3.Connection(s, user='CN=svc-gns3,OU=people,OU=gns3,DC=ad,DC=example,DC=org',
                         password='svcldap123', auto_bind=True, start_tls=True)
    print('BIND OK', c.extend.standard.who_am_i())
except Exception as e:
    print('EXC', type(e).__name__, ':', str(e)[:300])
PYEOF
echo '== message construction in gns3server:'
grep -rn "Failed to bind" /home/gns3/.venv/gns3server-venv/lib/python*/site-packages/gns3server/ 2>/dev/null | head -5
