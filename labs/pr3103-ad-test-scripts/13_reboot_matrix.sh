#!/bin/bash
# Reboot DC (LSASS re-scan with Root-trusted cert), wait for StartTLS green, run full matrix.
echo "=== reboot issued $(date '+%H:%M:%S') ==="
cd /tmp/ad-scripts
timeout 90 python3 -I ps.py <(printf '%s' 'Restart-Computer -Force; "ok"') 60 2>&1 | grep -E '^===' | head -2

echo "=== waiting for 389 to come back ==="
n=0
until nc -z -w 2 192.168.101.32 389 2>/dev/null; do
  n=$((n+1)); [ $n -gt 60 ] && echo 'FATAL: 389 never came back (5 min)' && exit 1
  sleep 5
done
echo "389 back after ~$((n*5))s; settling 60s"
sleep 60

echo "=== polling StartTLS until green ==="
n=0
until timeout 10 openssl s_client -connect 192.168.101.32:389 -starttls ldap -brief < /dev/null 2>&1 | grep -q 'Protocol version'; do
  n=$((n+1)); [ $n -gt 24 ] && echo 'FATAL: StartTLS still down after 4 min' && exit 1
  sleep 10
done
echo "=== StartTLS GREEN at $(date '+%H:%M:%S') ==="
timeout 10 openssl s_client -connect 192.168.101.32:389 -starttls ldap -brief < /dev/null 2>&1 | head -8
echo "=== LDAPS 636 check ==="
timeout 10 openssl s_client -connect 192.168.101.32:636 -brief < /dev/null 2>&1 | head -6

echo "=== running full GNS3 AD matrix ==="
python3 -I /tmp/ad-scripts/09_ad_matrix.py
echo "=== MATRIX SCRIPT DONE $(date '+%H:%M:%S') rc=$? ==="
