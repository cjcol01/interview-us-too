#!/usr/bin/env bash
# Startup script for interview-us-too — runs natively inside WSL/bash.
#
# Issue (2026-06-24): WSL2's Hyper-V network stack dynamically reserves port
# ranges on boot, sometimes grabbing port 6379. This blocks Redis. If Redis
# fails to connect, restart the Windows NAT driver as admin in PowerShell:
#   net stop winnat
#   net start winnat

set -e
cd "$(dirname "${BASH_SOURCE[0]}")"

PORT="${SERVER_PORT:-8000}"
PYTHON="./.venv/bin/python"
STRIPE_PID=""

cleanup() {
  echo -e "\n=== Shutting down ==="
  [ -n "$STRIPE_PID" ] && kill "$STRIPE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "=== Starting Redis ==="
if [ "$(redis-cli ping 2>/dev/null)" != "PONG" ]; then
  if [ "$(uname)" = "Darwin" ]; then
    # macOS: prefer Homebrew services, fall back to a daemonized redis-server.
    if command -v brew >/dev/null 2>&1; then
      brew services start redis
    else
      redis-server --daemonize yes
    fi
  else
    # Linux / WSL: sudo password may be required.
    sudo service redis-server start
  fi
  for _ in 1 2 3 4 5; do
    [ "$(redis-cli ping 2>/dev/null)" = "PONG" ] && break
    sleep 1
  done
fi
if [ "$(redis-cli ping 2>/dev/null)" = "PONG" ]; then
  echo "Redis: OK"
else
  echo "Redis did not respond to ping. Press Enter to continue anyway, or Ctrl+C to abort."
  read -r
fi

echo "=== Starting Stripe webhook listener ==="
if command -v stripe >/dev/null 2>&1; then
  stripe listen --forward-to "localhost:${PORT}/billing/webhook" &
  STRIPE_PID=$!
  sleep 2
  if kill -0 "$STRIPE_PID" 2>/dev/null; then
    echo "Stripe listener: running (pid $STRIPE_PID, check output above for webhook secret)"
  else
    echo "Stripe listener: FAILED TO START — check output above. Continuing without it (billing webhooks won't fire locally)."
    STRIPE_PID=""
  fi
else
  echo "Stripe CLI not found on PATH — skipping webhook listener (billing webhooks won't fire locally)."
  echo "Install: https://docs.stripe.com/stripe-cli"
fi

echo "=== Starting server ==="
RELOAD=1 "$PYTHON" server.py
