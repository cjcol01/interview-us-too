"""
Startup script for interview-us-too.

Issue (2026-06-24): WSL2's Hyper-V network stack dynamically reserves port
ranges on boot, sometimes grabbing port 6379. This blocks Redis — WSL port
forwarding and Docker both fail with "access permissions" errors. Redis starts
fine inside WSL but is unreachable from Windows localhost.

Fix: restart the Windows NAT driver as admin in PowerShell:
    net stop winnat
    net start winnat
This releases the reserved ports. Run this if Redis fails to connect.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

os.chdir(Path(__file__).parent)


def step(msg):
    print(f"\n=== {msg} ===")


def start_redis():
    step("Starting Redis in WSL (sudo password may be required)")
    subprocess.run(["wsl", "sudo", "service", "redis-server", "start"])

    check = subprocess.run(["wsl", "redis-cli", "ping"], capture_output=True, text=True)
    if check.stdout.strip() == "PONG":
        print("Redis: OK")
        return
    print("Redis did not respond to ping. Press Enter to continue anyway, or Ctrl+C to abort.")
    input()


def start_stripe():
    step("Starting Stripe webhook listener")
    proc = subprocess.Popen(
        ["stripe", "listen", "--forward-to", "localhost:8000/webhook"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    time.sleep(2)
    print("Stripe listener: running (check output above for webhook secret)")
    return proc


def start_server():
    step("Starting server")
    subprocess.run([sys.executable, "server.py"])


if __name__ == "__main__":
    stripe_proc = None
    try:
        start_redis()
        stripe_proc = start_stripe()
        start_server()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        if stripe_proc:
            stripe_proc.terminate()
