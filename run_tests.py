#!/usr/bin/env python3
"""
Test runner — replaces test_all.py.
Run with:  python run_tests.py  (or ./run_tests.py once chmod +x'd)
"""
import sys
import os

# Re-exec under the project venv's interpreter if invoked with a different one (e.g. the
# system `python3`, which has none of requirements.txt installed). Without this, running
# `python3 run_tests.py` fails on the first missing package (fastapi, then resend, then
# the next one...) instead of all at once, since the venv already has everything installed.
_venv_python = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "bin", "python")
if os.path.exists(_venv_python) and os.path.abspath(sys.executable) != os.path.abspath(_venv_python):
    os.execv(_venv_python, [_venv_python] + sys.argv)

sys.path.insert(0, os.path.dirname(__file__))

import warnings
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.CRITICAL)

os.environ.setdefault("TESTING", "1")  # use fakeredis + isolated Postgres schema — must be set before importing server
# Pin the admin account the _require_author tests log in as. Set here rather than read from
# .env so the suite doesn't depend on (or hardcode) the real ADMIN_USERNAME; load_dotenv()
# in config.py doesn't override an already-set var, so this wins.
os.environ.setdefault("ADMIN_USERNAME", "_test_admin")

# Start from a clean test database each run. Drop and recreate the public schema rather than
# just calling drop_all() — the five native Postgres ENUM types (AccountLevel, ResponseStyle,
# ReferralStatus, CommissionStatus, WithdrawalStatus) live outside any table and are NOT
# removed by drop_all(), so a second run would fail with "type already exists" on create_all().
from config import TEST_DATABASE_URL as _test_url
if not _test_url:
    print(
        "\nERROR: TEST_DATABASE_URL is not set. Provide a Postgres test database URL before running tests.\n"
        "\nQuick start:\n"
        "  docker run -d --name pg-iut -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16\n"
        "  export TEST_DATABASE_URL=postgresql://postgres:dev@localhost:5432/iut_test\n"
        "(create the iut_test database once: docker exec pg-iut createdb -U postgres iut_test)\n"
    )
    sys.exit(1)

import psycopg2 as _psycopg2
_pg = _psycopg2.connect(_test_url)
_pg.autocommit = True
_pgc = _pg.cursor()
_pgc.execute("DROP SCHEMA public CASCADE")
_pgc.execute("CREATE SCHEMA public")
_pgc.close()
_pg.close()
del _psycopg2, _pg, _pgc, _test_url

from tests.harness import BOLD, FAIL, PASS, RESET, SKIP, results, set_client, set_redis, skip, test


def section(title):
    pad = max(0, 44 - len(title))
    print(f"\n{BOLD}-- {title} {'─' * pad}{RESET}")


# Every route that sends a real email (register/resend-verification/forgot-password,
# admin ban/warn/announcement actions, account deletion, cancel feedback, ...) goes
# through this one call. Mocking it here protects the Resend daily quota by default —
# only the dedicated "Resend API connection" check below still hits the live API.
# Run `python run_tests.py 1` to disable the mock and let every route send for real.
RUN_ALL_EMAIL_TESTS = len(sys.argv) > 1 and sys.argv[1] == "1"

import mailer
_real_resend_send = mailer.resend.Emails.send


def _mocked_resend_send(*args, **kwargs):
    return {"id": "test-mocked-send"}


if RUN_ALL_EMAIL_TESTS:
    print(f"{BOLD}[full mode] every email-sending route will hit the live Resend API{RESET}")
else:
    mailer.resend.Emails.send = _mocked_resend_send
    print(f"{BOLD}[default mode] only the dedicated Resend check hits the live API "
          f"— pass '1' to test every email route for real{RESET}")


from fastapi.testclient import TestClient
from server import app

with TestClient(app) as client:
    set_client(client)
    set_redis(app.state.redis)

    section("Config")
    import tests.test_config
    tests.test_config.register(test, skip, client)

    section("Database")
    import tests.test_database
    tests.test_database.register(test, skip, client)

    section("Auth")
    import tests.test_auth
    tests.test_auth.register(test, skip, client)

    section("Interview Sessions")
    import tests.test_sessions
    tests.test_sessions.register(test, skip, client)

    section("Billing — Unit")
    import tests.test_billing
    tests.test_billing.register(test, skip, client)

    section("HTTP Routes")
    import tests.test_routes
    tests.test_routes.register(test, skip, client)

    section("Account Settings")
    import tests.test_account
    tests.test_account.register(test, skip, client)

    section("Mobile Login")
    import tests.test_mobile_login
    tests.test_mobile_login.register(test, skip, client)

    section("Install Link / Device Handoff")
    import tests.test_install_link
    tests.test_install_link.register(test, skip, client)

    section("Google OAuth")
    import tests.test_google_oauth
    tests.test_google_oauth.register(test, skip, client)

    section("GitHub OAuth")
    import tests.test_github_oauth
    tests.test_github_oauth.register(test, skip, client)

    section("Rate Limiting")
    import tests.test_rate_limit
    tests.test_rate_limit.register(test, skip, client)

    section("Referrals")
    import tests.test_referrals
    tests.test_referrals.register(test, skip, client)

    section("Billing — HTTP")
    tests.test_billing.register_http(test, skip, client)

    section("Partner Programme")
    import tests.test_partner
    tests.test_partner.register(test, skip, client)

    section("Author Page")
    import tests.test_author
    tests.test_author.register(test, skip, client)

    section("Admin Routes")
    import tests.test_admin
    tests.test_admin.register(test, skip, client)

    section("Admin — Home")
    import tests.test_admin_home
    tests.test_admin_home.register(test, skip, client)

    section("Admin — Growth Dashboard")
    import tests.test_dashboard
    tests.test_dashboard.register(test, skip, client)

    section("Admin — Leads")
    import tests.test_admin_leads
    tests.test_admin_leads.register(test, skip, client)

    section("Admin — System Health")
    import tests.test_health
    tests.test_health.register(test, skip, client)

    section("Admin Health — Metrics")
    import tests.test_metrics
    tests.test_metrics.register(test, skip, client)

    section("Admin — Announcements")
    import tests.test_announcements
    tests.test_announcements.register(test, skip, client)

    section("Hotkeys")
    import tests.test_hotkeys
    tests.test_hotkeys.register(test, skip, client)

    section("Instant Replay")
    import tests.test_replay
    tests.test_replay.register(test, skip, client)

    section("Response Style, Complexity & Comment Level API")
    import tests.test_response_style
    tests.test_response_style.register(test, skip, client)

    section("Interview Context")
    import tests.test_context
    tests.test_context.register(test, skip, client)

    section("Audio Capture")
    import tests.test_audio
    tests.test_audio.register(test, skip, client)

    section("AI Fallback")
    import tests.test_ai_fallback
    tests.test_ai_fallback.register(test, skip, client)

    section("Session History")
    import tests.test_session_history
    tests.test_session_history.register(test, skip, client)

    section("Typing Mode")
    import tests.test_typing
    tests.test_typing.register(test, skip, client)

    section("Session Feedback")
    import tests.test_session_feedback
    tests.test_session_feedback.register(test, skip, client)

    section("External APIs")

    def _test_claude():
        import anthropic
        from config import ANTHROPIC_API_KEY
        c = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        r = c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with only: ok"}],
        )
        assert r.content[0].text.strip().lower().startswith("ok")

    def _test_stripe():
        import stripe
        from config import STRIPE_SECRET_KEY
        if not STRIPE_SECRET_KEY or STRIPE_SECRET_KEY.startswith("sk_test_..."):
            raise AssertionError("Stripe key not configured")
        stripe.api_key = STRIPE_SECRET_KEY
        # stripe>=15's ListObject only supports string-keyed __getitem__, not the
        # sequence-style int indexing dict() falls back to for non-mapping iterables —
        # dict(...) raises KeyError: 0 here. `in` uses __contains__ and works fine.
        assert "data" in stripe.Product.list(limit=1)

    def _test_resend():
        # The one deliberate live send per run (see the mock installed near the top of
        # this file) — confirms the Resend API key/wiring still works end to end.
        from config import NOTIFY_EMAIL
        mailer.resend.Emails.send = _real_resend_send
        try:
            mailer.send_verification_email(NOTIFY_EMAIL, "run-tests-canary-token")
        finally:
            if not RUN_ALL_EMAIL_TESTS:
                mailer.resend.Emails.send = _mocked_resend_send

    test("Claude API connection and response", _test_claude)
    test("Stripe API connection",              _test_stripe)
    test("Resend API connection (live email)", _test_resend)

    section("Server Modules")

    def _test_imports():
        import auth    # noqa
        import billing  # noqa
        import models   # noqa
        import server   # noqa

    test("All server modules import cleanly", _test_imports)


# ---------------------------------------------------------------------------
passed  = sum(1 for _, r, _ in results if r is True)
failed  = sum(1 for _, r, _ in results if r is False)
skipped = sum(1 for _, r, _ in results if r is None)

print(f"\n{BOLD}{'─' * 48}{RESET}")
print(f"  {PASS} {passed}   {FAIL} {failed}   {SKIP} {skipped}")

failures = [(name, exc) for name, r, exc in results if r is False]
if failures:
    print(f"\n{BOLD}Failed tests:{RESET}")
    for name, exc in failures:
        print(f"  {FAIL} {name}")
        if exc is not None:
            print(f"         {type(exc).__name__}: {exc}")
print()

sys.exit(1 if failed else 0)
