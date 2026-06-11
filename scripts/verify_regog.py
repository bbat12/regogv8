#!/usr/bin/env python3
"""One-shot verifier: start serve_report.py, wait, curl, report, stop."""
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

os.chdir("/workspaces/regogv8")

# Start the app
log = open("/tmp/regog-app.log", "w")
proc = subprocess.Popen(
    [sys.executable, "serve_report.py"],
    stdout=log, stderr=subprocess.STDOUT,
    preexec_fn=os.setsid,  # new process group
)
print(f"Started PID {proc.pid}")

# Wait for boot
time.sleep(5)

# Check if still alive
if proc.poll() is not None:
    log.close()
    with open("/tmp/regog-app.log") as f:
        print("=== App died early. Log: ===")
        print(f.read())
    sys.exit(1)

# Curl
try:
    req = urllib.request.urlopen("http://localhost:8080/", timeout=5)
    body = req.read().decode("utf-8", errors="replace")
    print(f"HTTP {req.status}")
    print(f"Body length: {len(body)} bytes")
    print("=== First 800 chars of body ===")
    print(body[:800])
    print("=== Title detection ===")
    if "REGOG" in body or "regog" in body.lower():
        print("OK: REGOG content detected in response")
    else:
        print("FAIL: REGOG content NOT found in response")
except urllib.error.URLError as e:
    print(f"HTTP request failed: {e}")
    log.close()
    with open("/tmp/regog-app.log") as f:
        print("=== Log: ===")
        print(f.read())
    proc.terminate()
    sys.exit(1)

# Show log
log.close()
with open("/tmp/regog-app.log") as f:
    log_content = f.read()
print("=== App log (last 1500 chars) ===")
print(log_content[-1500:] if len(log_content) > 1500 else log_content)

# Stop the app
try:
    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    proc.wait(timeout=3)
except Exception:
    proc.kill()

print("=== Done ===")
