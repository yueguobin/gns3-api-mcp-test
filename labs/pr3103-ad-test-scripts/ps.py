#!/usr/bin/env python3
"""WinRM runner: execute a .ps1 file on GNS3-AD (192.168.101.32) via pywinrm NTLM."""
import sys
import winrm

URL = 'http://192.168.101.32:5985/wsman'
AUTH = ('administrator', 'Huawei@123')


def sess(read_to=120):
    s = winrm.Session(URL, auth=AUTH, transport='ntlm')
    s.read_timeout_sec = read_to
    s.operation_timeout_sec = max(read_to - 5, 30)
    return s


def run_ps_code(code, read_to=120):
    s = sess(read_to)
    r = s.run_ps(code if isinstance(code, str) else code.decode('utf-8'))
    return r


def run_ps_file(path, read_to=120):
    with open(path, 'rb') as f:
        payload = f.read()
    return run_ps_code(payload, read_to)


def dump(r, err_limit=1500):
    print('=== rc:', r.status_code)
    print(r.std_out.decode('utf-8', 'replace'))
    err = r.std_err.decode('utf-8', 'replace')
    if err.strip():
        print('=== stderr:')
        print(err[:err_limit])


if __name__ == '__main__':
    path = sys.argv[1]
    to = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    dump(run_ps_file(path, to))
    sys.exit(0)
