"""Locust load test for the interview-us-too dev server.

Simulates two kinds of traffic against a locally running `python server.py`:

  AnonymousBrowser   - unauthenticated page browsing (landing, pricing, faq, login).
  AuthenticatedUser  - starts with an already-valid session cookie for a seeded
                       free-tier test account, then navigates authenticated
                       pages/APIs and fires a "mock capture" request.

Zero-cost guarantee for the capture endpoint:
    /api/capture runs _gate_basic_access() (server.py) BEFORE any Anthropic call and
    returns 403 for free-tier accounts. Every account in accounts.json is asserted to
    be `free` at import time below, so mock_capture() can never reach a paid API.

Run:
    python loadtest/seed_users.py --count 50   # once, produces accounts.json
    locust -f loadtest/locustfile.py --host http://localhost:8000
"""
import json
import os
import random
from pathlib import Path

from locust import HttpUser, LoadTestShape, between, task

ACCOUNTS_FILE = Path(__file__).resolve().parent / "accounts.json"

# IMPORTANT: defining a LoadTestShape subclass makes Locust ignore -u/-r/-t entirely
# and run the shape's own schedule instead. That's exactly what we want for the real
# breaking-point run, but it means a plain `-u 3 -t 20s` smoke test would silently be
# hijacked into the full ramp. So the shape only exists when explicitly requested.
RAMP_ENABLED = os.environ.get("LOADTEST_RAMP") == "1"

# --- ramp shape: hold each user count for STEP_TIME seconds, then step up -----------
# Evenly spaced (+STEP_SIZE per step) rather than doubling, so a big burst of new
# spawns doesn't land in one go and obscure whether the breaking point tracks
# total concurrency or the size of each spawn burst.
#
# Open-ended: no upper cap on user count. Keeps ramping until you stop it (web UI
# stop button or Ctrl-C) once you see it break — this is a find-the-ceiling run,
# not a fixed-size test.
STEP_START = 25           # first step's user count
STEP_SIZE = 25            # users added per step
STEP_TIME = 40            # seconds held at each level
STEP_SPAWN_RATE = 10      # users spawned/stopped per second between steps

# --- traffic mix: fraction of virtual users that are anonymous vs authenticated ----
ANON_WEIGHT = 7
AUTH_WEIGHT = 3


def _load_accounts():
    if not ACCOUNTS_FILE.exists():
        raise SystemExit(
            f"{ACCOUNTS_FILE} not found. Run `python loadtest/seed_users.py --count N` first."
        )
    accounts = json.loads(ACCOUNTS_FILE.read_text())
    if not accounts:
        raise SystemExit(f"{ACCOUNTS_FILE} is empty. Seed some users first.")
    non_free = [a["username"] for a in accounts if a.get("account_level") != "free"]
    if non_free:
        raise SystemExit(
            "Refusing to run: accounts.json contains non-free account(s): "
            f"{non_free}. Only free-tier accounts are safe for mock_capture "
            "(they 403 at the gate before any AI call). Re-seed with seed_users.py."
        )
    if not all("session_token" in a for a in accounts):
        raise SystemExit(
            "accounts.json is missing 'session_token' entries (from an older "
            "seed_users.py run). Re-run `seed_users.py --count N` to regenerate it."
        )
    return accounts


ACCOUNTS = _load_accounts()


class AnonymousBrowser(HttpUser):
    """Unauthenticated visitor browsing public pages."""

    weight = ANON_WEIGHT
    wait_time = between(1, 3)

    @task(3)
    def landing(self):
        self.client.get("/", name="/")

    @task(2)
    def pricing(self):
        self.client.get("/pricing", name="/pricing")

    @task(1)
    def faq(self):
        self.client.get("/faq", name="/faq")

    @task(1)
    def login_page(self):
        self.client.get("/login", name="/login [page]")

    @task(1)
    def partner(self):
        self.client.get("/partner", name="/partner")


class AuthenticatedUser(HttpUser):
    """Logged-in free-tier user navigating the dashboard/settings and firing captures."""

    weight = AUTH_WEIGHT
    wait_time = between(1, 3)

    def on_start(self):
        account = random.choice(ACCOUNTS)
        self.api_token = account["api_token"]
        # Already-valid session cookie minted offline by seed_users.py — no
        # /auth/login call, so no bcrypt check on the request path.
        self.client.cookies.set("session", account["session_token"])

    @task(3)
    def settings_page(self):
        self.client.get("/settings", name="/settings")

    @task(3)
    def api_me(self):
        self.client.get(
            "/api/me",
            headers={"Authorization": f"Bearer {self.api_token}"},
            name="/api/me",
        )

    @task(2)
    def trial_status(self):
        self.client.get("/api/trial/status", name="/api/trial/status")

    @task(2)
    def billing_status(self):
        self.client.get("/api/billing/status", name="/api/billing/status")

    @task(2)
    def app_dashboard(self):
        # Free-tier accounts get redirected off /app; still a full auth+DB round trip.
        self.client.get("/app", name="/app", allow_redirects=False)

    @task(1)
    def mock_capture(self):
        # Free-tier -> _gate_basic_access() 403s before any Anthropic call is made.
        with self.client.post(
            "/api/capture",
            json={"image": "AAAA"},
            headers={"Authorization": f"Bearer {self.api_token}"},
            name="/api/capture [mock, expect 403]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 403:
                resp.success()
            elif resp.status_code >= 500:
                resp.failure(f"server error {resp.status_code}")
            else:
                # Unexpected: e.g. a seeded account isn't actually free anymore.
                resp.failure(f"unexpected status {resp.status_code}")


if RAMP_ENABLED:
    class StepLoadShape(LoadTestShape):
        """Ramp user count up in steps, with no upper cap, until you stop it.

        Holds each level for STEP_TIME seconds, then adds STEP_SIZE more users,
        indefinitely. This is a find-the-ceiling run, not a fixed-size test — stop
        it yourself (web UI stop button or Ctrl-C) once you see p95/p99 latency and
        failure rate spike in http://localhost:8089 or the --csv output.

        Only defined when LOADTEST_RAMP=1 is set — merely importing a LoadTestShape
        subclass makes Locust ignore -u/-r/-t and run this schedule instead, which
        would otherwise hijack an innocent smoke-test invocation.
        """

        def tick(self):
            run_time = self.get_run_time()
            step = int(run_time // STEP_TIME)
            users = STEP_START + step * STEP_SIZE
            return (users, STEP_SPAWN_RATE)
