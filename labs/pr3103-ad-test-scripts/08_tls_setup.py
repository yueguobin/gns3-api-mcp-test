#!/usr/bin/env python3
"""Fetch AD self-signed cert from GNS3-AD, install as CA on VM21 + hosts entry."""
import base64
import os
import subprocess
import sys

sys.path.insert(0, '/tmp/ad-scripts')
from ps import sess  # noqa: E402

s = sess(60)
r = s.run_cmd('type C:\\Windows\\Temp\\ad-lab-root.b64')
if r.status_code != 0:
    print('type failed rc', r.status_code, r.std_err.decode(errors='replace')[:500])
    sys.exit(1)
b64text = r.std_out.decode(errors='replace').strip()
b64_lines = [l.strip() for l in b64text.splitlines() if l.strip() and 'BEGIN' not in l and 'END' not in l]
pem = '-----BEGIN CERTIFICATE-----\n' + '\n'.join(b64_lines) + '\n-----END CERTIFICATE-----\n'
with open('/tmp/ad-scripts/ad-lab-root.pem', 'w') as f:
    f.write(pem)
print('PEM written to /tmp/ad-scripts/ad-lab-root.pem,', len(pem), 'bytes')

env = dict(os.environ, SSH_ASKPASS='/tmp/vm21askpass.sh', SSH_ASKPASS_REQUIRE='force', DISPLAY=':0')
pem_b64 = base64.b64encode(pem.encode()).decode()
cmd = (
    f"printf '%s' '{pem_b64}' | base64 -d | sudo tee /usr/local/share/ca-certificates/ad-lab-root.crt >/dev/null && echo CERT_INSTALLED; "
    "sudo grep -q 'ad.example.org' /etc/hosts || echo '192.168.101.32 ad.example.org gns3-ad.ad.example.org' | sudo tee -a /etc/hosts >/dev/null; "
    "sudo update-ca-certificates 2>&1 | tail -1; "
    "getent hosts ad.example.org; tail -1 /etc/hosts"
)
p = subprocess.run(['setsid', 'ssh', '-o', 'StrictHostKeyChecking=accept-new', 'gns3@192.168.101.21', cmd],
                   env=env, capture_output=True, text=True, timeout=180)
print('VM21 rc', p.returncode)
print(p.stdout)
if p.stderr.strip():
    print('stderr tail:', p.stderr[-600:])
