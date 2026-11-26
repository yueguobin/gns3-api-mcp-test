#!/usr/bin/env python3
"""PR #3103 retest — Phase 4 helper: poll alice login until the directory is back.

Run AFTER restarting the OpenLDAP-1 GNS3 node (container rebuild + slapd boot
takes tens of seconds). Polls POST /v3/access/users/authenticate for alice.

Note: during a directory outage every failed login counts toward the rate
limiter (5 attempts / 60s per username) — a 429 here means the limiter, not
necessarily that the directory is still down. Wait out the window or poll with
a different (unused) username.

Usage: python3 04_dr_recover_wait.py [BASE_URL] [TIMEOUT_S]
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://192.168.101.21"
TIMEOUT = int(sys.argv[2]) if len(sys.argv) > 2 else 90

start = time.time()
deadline = start + TIMEOUT
attempt = 0
while time.time() < deadline:
    attempt += 1
    r = urllib.request.Request(BASE + "/v3/access/users/authenticate", method="POST")
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, json.dumps({"username": "alice", "password": "gns3test"}).encode(), timeout=12) as resp:
            print(f"attempt {attempt} (t+{time.time()-start:.1f}s): status={resp.status}  <- directory back")
            break
    except urllib.error.HTTPError as e:
        print(f"attempt {attempt} (t+{time.time()-start:.1f}s): status={e.code}" + ("  (429 = rate limiter, not outage)" if e.code == 429 else ""))
    except Exception as e:
        print(f"attempt {attempt} (t+{time.time()-start:.1f}s): {type(e).__name__}")
    time.sleep(5)
else:
    print(f"TIMEOUT: no successful login within {TIMEOUT}s")
