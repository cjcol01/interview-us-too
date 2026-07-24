"""Google OAuth ("Continue with Google") — server._google_exchange_claims is monkeypatched
in every test below so nothing here calls the real Google token endpoint; only the
state-stash-in-Redis + user-resolution logic in server.py's /auth/google* routes is
exercised. Requires TESTING=1 (fakeredis) like the rest of the suite."""
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import secrets as _sec


def register(test, skip, client):
    import server
    from auth import verify_password
    from database import SessionLocal
    from models import AccountLevel, User
    from tests.helpers import cleanup, make_user

    def _claims(email, sub, name="Test Googler"):
        return {"sub": sub, "email": email, "email_verified": True, "name": name}

    def _start_google_flow(ref_cookie=None):
        cookies = {"ref": ref_cookie} if ref_cookie else {}
        r = client.get("/auth/google", cookies=cookies, follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers["location"]
        assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth")
        return parse_qs(urlparse(loc).query)["state"][0]

    def test_routes_404_when_disabled():
        # Force the disabled state rather than relying on the ambient .env — a dev
        # checkout with real GOOGLE_CLIENT_ID/SECRET configured would otherwise fail here.
        orig_enabled = server.GOOGLE_OAUTH_ENABLED
        server.GOOGLE_OAUTH_ENABLED = False
        try:
            r1 = client.get("/auth/google", follow_redirects=False)
            r2 = client.get("/auth/google/callback?code=x&state=y", follow_redirects=False)
            assert r1.status_code == 404
            assert r2.status_code == 404
        finally:
            server.GOOGLE_OAUTH_ENABLED = orig_enabled

    def test_new_email_creates_verified_trial_user_and_consumes_referral():
        db = SessionLocal()
        referrer = new_user = None
        orig_enabled, orig_exchange = server.GOOGLE_OAUTH_ENABLED, server._google_exchange_claims
        try:
            server.GOOGLE_OAUTH_ENABLED = True
            referrer = make_user(db, AccountLevel.trial)
            tag = _sec.token_hex(4)
            email = f"_test_google_{tag}@test.internal"
            sub = f"google-sub-{tag}"
            server._google_exchange_claims = AsyncMock(return_value=_claims(email, sub))

            state = _start_google_flow(ref_cookie=referrer.referral_code)
            r = client.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)
            assert r.status_code == 303
            assert "/app" in r.headers.get("location", "")
            assert "session" in r.cookies

            new_user = db.query(User).filter(User.email == email).first()
            assert new_user is not None
            assert new_user.google_id == sub
            assert new_user.email_verified is True
            assert new_user.account_level == AccountLevel.trial
            assert new_user.username
            assert new_user.referred_by_id == referrer.id
        finally:
            server.GOOGLE_OAUTH_ENABLED, server._google_exchange_claims = orig_enabled, orig_exchange
            cleanup(db, new_user, referrer); db.close()

    def test_same_sub_logs_into_same_user_no_duplicate():
        db = SessionLocal()
        user = None
        orig_enabled, orig_exchange = server.GOOGLE_OAUTH_ENABLED, server._google_exchange_claims
        try:
            server.GOOGLE_OAUTH_ENABLED = True
            tag = _sec.token_hex(4)
            email = f"_test_google_{tag}@test.internal"
            sub = f"google-sub-{tag}"
            server._google_exchange_claims = AsyncMock(return_value=_claims(email, sub))

            state1 = _start_google_flow()
            r1 = client.get(f"/auth/google/callback?code=abc&state={state1}", follow_redirects=False)
            assert r1.status_code == 303
            user = db.query(User).filter(User.email == email).first()
            assert user is not None

            state2 = _start_google_flow()
            r2 = client.get(f"/auth/google/callback?code=abc&state={state2}", follow_redirects=False)
            assert r2.status_code == 303

            matches = db.query(User).filter(User.email == email).all()
            assert len(matches) == 1
            assert matches[0].id == user.id
        finally:
            server.GOOGLE_OAUTH_ENABLED, server._google_exchange_claims = orig_enabled, orig_exchange
            cleanup(db, user); db.close()

    def test_matching_verified_email_links_without_touching_password():
        db = SessionLocal()
        user = None
        orig_enabled, orig_exchange = server.GOOGLE_OAUTH_ENABLED, server._google_exchange_claims
        try:
            server.GOOGLE_OAUTH_ENABLED = True
            user = make_user(db, AccountLevel.trial)
            user.email_verified = True
            db.commit()
            old_hash = user.password_hash
            sub = f"google-sub-{_sec.token_hex(4)}"
            server._google_exchange_claims = AsyncMock(return_value=_claims(user.email, sub))

            state = _start_google_flow()
            r = client.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)
            assert r.status_code == 303

            db.refresh(user)
            assert user.google_id == sub
            assert user.password_hash == old_hash
            assert verify_password("testpass123", user.password_hash)
        finally:
            server.GOOGLE_OAUTH_ENABLED, server._google_exchange_claims = orig_enabled, orig_exchange
            cleanup(db, user); db.close()

    def test_matching_unverified_email_links_and_invalidates_old_password():
        db = SessionLocal()
        user = None
        orig_enabled, orig_exchange = server.GOOGLE_OAUTH_ENABLED, server._google_exchange_claims
        try:
            server.GOOGLE_OAUTH_ENABLED = True
            user = make_user(db, AccountLevel.trial)  # email_verified defaults to False
            assert user.email_verified is False
            sub = f"google-sub-{_sec.token_hex(4)}"
            server._google_exchange_claims = AsyncMock(return_value=_claims(user.email, sub))

            state = _start_google_flow()
            r = client.get(f"/auth/google/callback?code=abc&state={state}", follow_redirects=False)
            assert r.status_code == 303

            db.refresh(user)
            assert user.google_id == sub
            assert user.email_verified is True
            assert not verify_password("testpass123", user.password_hash)
        finally:
            server.GOOGLE_OAUTH_ENABLED, server._google_exchange_claims = orig_enabled, orig_exchange
            cleanup(db, user); db.close()

    def test_bad_state_redirects_to_login_error():
        orig_enabled = server.GOOGLE_OAUTH_ENABLED
        try:
            server.GOOGLE_OAUTH_ENABLED = True
            r = client.get("/auth/google/callback?code=abc&state=not-a-real-state", follow_redirects=False)
            assert r.status_code == 303
            assert "error=oauth_failed" in r.headers.get("location", "")
        finally:
            server.GOOGLE_OAUTH_ENABLED = orig_enabled

    def test_cancelled_consent_redirects_to_login_error():
        orig_enabled = server.GOOGLE_OAUTH_ENABLED
        try:
            server.GOOGLE_OAUTH_ENABLED = True
            r = client.get("/auth/google/callback?error=access_denied", follow_redirects=False)
            assert r.status_code == 303
            assert "error=oauth_failed" in r.headers.get("location", "")
        finally:
            server.GOOGLE_OAUTH_ENABLED = orig_enabled

    test("GET /auth/google* -> 404 when Google OAuth is disabled",                  test_routes_404_when_disabled)
    test("Google callback: new email -> verified trial user + referral",            test_new_email_creates_verified_trial_user_and_consumes_referral)
    test("Google callback: same sub twice -> logs into same user, no duplicate",    test_same_sub_logs_into_same_user_no_duplicate)
    test("Google callback: verified existing email -> links, password kept",        test_matching_verified_email_links_without_touching_password)
    test("Google callback: unverified existing email -> links, old password dead", test_matching_unverified_email_links_and_invalidates_old_password)
    test("Google callback: unknown/expired state -> login?error=oauth_failed",      test_bad_state_redirects_to_login_error)
    test("Google callback: consent denied -> login?error=oauth_failed",             test_cancelled_consent_redirects_to_login_error)
