#!/usr/bin/env python3
"""Start ngrok tunnel and the app server together."""
import os
import subprocess
import sys
import time
import urllib.request
import json
from pathlib import Path

# Use the Python interpreter that has the app's dependencies installed
_candidates = [
    Path("/mnt/d/Crap/Python/python.exe"),
    Path(__file__).parent / ".venv" / "bin" / "python",
]
PYTHON = next((str(p) for p in _candidates if p.exists()), sys.executable)

PORT = int(os.getenv("SERVER_PORT", 8000))

# Kill any leftover ngrok from a previous run
subprocess.run(["pkill", "-f", "ngrok"], capture_output=True)
time.sleep(0.5)

ngrok = subprocess.Popen(
    ["ngrok", "http", str(PORT), "--log=false"],
    stderr=subprocess.DEVNULL,
)

# Wait for ngrok API to be ready (up to 20 seconds)
public_url = None
time.sleep(2)  # give ngrok a moment to establish the tunnel session
for _ in range(36):
    try:
        with urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=2) as r:
            data = json.load(r)
        tunnels = data.get("tunnels", [])
        if tunnels:
            public_url = tunnels[0]["public_url"]
            for t in tunnels:
                if t["public_url"].startswith("https"):
                    public_url = t["public_url"]
                    break
            break
    except Exception:
        time.sleep(0.5)

if not public_url:
    print("Could not get ngrok URL — is ngrok authenticated? Run: ngrok authtoken <your-token>")
    ngrok.terminate()
    sys.exit(1)

print(f"\n  Public URL: {public_url}\n")
print("  Set BASE_URL in .env to that value to make email links work remotely.\n")

# Patch BASE_URL for this process so emails use the public URL
os.environ["BASE_URL"] = public_url

server = subprocess.Popen([PYTHON, "server.py"])
try:
    server.wait()
except KeyboardInterrupt:
    pass
finally:
    server.terminate()
    ngrok.terminate()
