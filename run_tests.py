"""
Test runner — replaces test_all.py.
Run with:  python run_tests.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import warnings
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.CRITICAL)

os.environ.setdefault("TESTING", "1")  # use fakeredis — must be set before importing server

from tests.harness import BOLD, FAIL, PASS, RESET, SKIP, results, skip, test


def section(title):
    pad = max(0, 44 - len(title))
    print(f"\n{BOLD}-- {title} {'─' * pad}{RESET}")


from fastapi.testclient import TestClient
from server import app

with TestClient(app) as client:

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

    section("Referrals")
    import tests.test_referrals
    tests.test_referrals.register(test, skip, client)

    section("Billing — HTTP")
    tests.test_billing.register_http(test, skip, client)

    section("Author Page")
    import tests.test_author
    tests.test_author.register(test, skip, client)

    section("Hotkeys")
    import tests.test_hotkeys
    tests.test_hotkeys.register(test, skip, client)

    section("Instant Replay")
    import tests.test_replay
    tests.test_replay.register(test, skip, client)

    section("Response Style & Complexity API")
    import tests.test_response_style
    tests.test_response_style.register(test, skip, client)

    section("Audio Capture")
    import tests.test_audio
    tests.test_audio.register(test, skip, client)

    section("Typing Mode")
    import tests.test_typing
    tests.test_typing.register(test, skip, client)

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
        assert "data" in dict(stripe.Product.list(limit=1))

    test("Claude API connection and response", _test_claude)
    test("Stripe API connection",              _test_stripe)

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
