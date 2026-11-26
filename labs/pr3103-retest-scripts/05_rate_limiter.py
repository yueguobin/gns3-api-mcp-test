#!/usr/bin/env python3
"""PR #3103 retest — Phase 5: login rate limiter (test 10). Run LAST — it
deliberately burns failed-login budget for user 'dave' and blocks that
username for ~60s.

Sequence: 5 wrong passwords -> 401 each; 6th attempt (correct password) -> 429;
still inside window -> 429; poll every 5s -> 200 at ~t+60s (sliding window).

Failed logins caused by LDAP connection failures count too (observed during
outage recovery) — one more reason to run this when the directory is healthy.

Usage: python3 05_rate_limiter.py [BASE_URL]
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.101.21"


def login(user, pwd, timeout=12):
    r = urllib.request.Request(BASE + "/v3/access/users/authenticate", method="POST")
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, json.dumps({"username": user, "password": pwd}).encode(), timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


print("phase 1: five wrong passwords for dave (expect 401 each)")
codes = [login("dave", "wrongpass") for _ in range(5)]
print("  ->", codes)

print("phase 2: 6th attempt with CORRECT password (expect 429)")
print("  ->", login("dave", "gns3test"))

print("phase 3: still inside window, correct password again (expect 429)")
print("  ->", login("dave", "gns3test"))

print("phase 4: poll until window expires (expect 200 unblock at ~t+60s)")
start = time.time()
while time.time() - start < 90:
    time.sleep(5)
    st = login("dave", "gns3test")
    print(f"  t+{time.time()-start:.0f}s -> {st}")
    if st == 200:
        print("UNBLOCKED: dave login 200")
        break
else:
    print("TIMEOUT: still limited after 90s")
