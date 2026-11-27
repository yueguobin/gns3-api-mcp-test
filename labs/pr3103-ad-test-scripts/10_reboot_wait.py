#!/usr/bin/env python3
"""Reboot the DC so LSASS re-scans LocalMachine\\My and picks up the LDAPS cert,
then wait for WinRM to come back."""
import time
import sys

sys.path.insert(0, '/tmp/ad-scripts')
from ps import sess  # noqa: E402

LOG = '/tmp/ad-scripts/reboot.log'


def log(m):
    with open(LOG, 'a') as f:
        f.write(f'[{time.strftime("%H:%M:%S")}] {m}\n')


def main():
    s = sess(60)
    try:
        r = s.run_ps('Restart-Computer -Force; "reboot issued"')
        log(f'reboot cmd rc={r.status_code} out={r.std_out.decode(errors="replace").strip()}')
    except Exception as e:
        log(f'reboot cmd EXC (expected if connection cut): {type(e).__name__}')

    log('polling for WinRM back...')
    up = False
    for i in range(40):  # up to 10 min
        time.sleep(15)
        try:
            s = sess(30)
            r = s.run_ps('"pong $env:COMPUTERNAME"')
            if r.status_code == 0:
                log(f'WinRM back after ~{(i + 1) * 15}s')
                up = True
                break
        except Exception as e:
            log(f'poll {i}: {type(e).__name__}')
    if not up:
        log('FATAL: never came back')
        return 1
    time.sleep(60)  # let NTDS/ADWS settle
    try:
        s = sess(60)
        r = s.run_ps('(Get-Service NTDS,kdc).Status -join ","')
        log(f'services NTDS,kdc = {r.std_out.decode(errors="replace").strip()}')
    except Exception as e:
        log(f'service check EXC: {type(e).__name__}')
    log('REBOOT_CYCLE_DONE')
    return 0


sys.exit(main())
