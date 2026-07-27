"""GitHub OAuth ("Continue with GitHub") — server._github_exchange_claims is monkeypatched
in every test below so nothing here calls the real GitHub API; only the state-stash-in-Redis
+ user-resolution logic in server.py's /auth/github* routes is exercised. Requires TESTING=1
(fakeredis) like the rest of the suite."""
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import secrets as _sec


def register(test, skip, client):
    import server
    from auth import verify_password
    from database import SessionLocal
    from models import AccountLevel, User
    from tests.helpers import cleanup, make_user

    def _claims(email, sub, name="Test Hubber", email_verified=True):
        return {"sub": sub, "email": email, "email_verified": email_verified, "name": name}

    def _start_github_flow(ref_cookie=None):
        cookies = {"ref": ref_cookie} if ref_cookie else {}
        r = client.get("/auth/github", cookies=cookies, follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers["location"]
        assert loc.startswith("https://github.com/login/oauth/authorize")
        return parse_qs(urlparse(loc).query)["state"][0]

    def test_routes_404_when_disabled():
        # Force the disabled state rather than relying on the ambient .env — a dev
        # checkout with real GITHUB_CLIENT_ID/SECRET configured would otherwise fail here.
        orig_enabled = server.GITHUB_OAUTH_ENABLED
        server.GITHUB_OAUTH_ENABLED = False
        try:
            r1 = client.get("/auth/github", follow_redirects=False)
            r2 = client.get("/auth/github/callback?code=x&state=y", follow_redirects=False)
            assert r1.status_code == 404
            assert r2.status_code == 404
        finally:
            server.GITHUB_OAUTH_ENABLED = orig_enabled

    def test_new_email_creates_verified_trial_user_and_consumes_referral():
        db = SessionLocal()
        referrer = new_user = None
        orig_enabled, orig_exchange = server.GITHUB_OAUTH_ENABLED, server._github_exchange_claims
        try:
            server.GITHUB_OAUTH_ENABLED = True
            referrer = make_user(db, AccountLevel.trial)
            tag = _sec.token_hex(4)
            email = f"_test_github_{tag}@test.internal"
            sub = f"github-sub-{tag}"
            server._github_exchange_claims = AsyncMock(return_value=_claims(email, sub))

            state = _start_github_flow(ref_cookie=referrer.referral_code)
            r = client.get(f"/auth/github/callback?code=abc&state={state}", follow_redirects=False)
            assert r.status_code == 303
            assert "/app" in r.headers.get("location", "")
            assert "session" in r.cookies

            new_user = db.query(User).filter(User.email == email).first()
            assert new_user is not None
            assert new_user.github_id == sub
            assert new_user.email_verified is True
            assert new_user.account_level == AccountLevel.trial
            assert new_user.username
            assert new_user.referred_by_id == referrer.id
        finally:
            server.GITHUB_OAUTH_ENABLED, server._github_exchange_claims = orig_enabled, orig_exchange
            cleanup(db, new_user, referrer); db.close()

    def test_same_sub_logs_into_same_user_no_duplicate():
        db = SessionLocal()
        user = None
        orig_enabled, orig_exchange = server.GITHUB_OAUTH_ENABLED, server._github_exchange_claims
        try:
            server.GITHUB_OAUTH_ENABLED = True
            tag = _sec.token_hex(4)
            email = f"_test_github_{tag}@test.internal"
            sub = f"github-sub-{tag}"
            server._github_exchange_claims = AsyncMock(return_value=_claims(email, sub))

            state1 = _start_github_flow()
            r1 = client.get(f"/auth/github/callback?code=abc&state={state1}", follow_redirects=False)
            assert r1.status_code == 303
            user = db.query(User).filter(User.email == email).first()
            assert user is not None

            state2 = _start_github_flow()
            r2 = client.get(f"/auth/github/callback?code=abc&state={state2}", follow_redirects=False)
            assert r2.status_code == 303

            matches = db.query(User).filter(User.email == email).all()
            assert len(matches) == 1
            assert matches[0].id == user.id
        finally:
            server.GITHUB_OAUTH_ENABLED, server._github_exchange_claims = orig_enabled, orig_exchange
            cleanup(db, user); db.close()

    def test_matching_verified_email_links_without_touching_password():
        db = SessionLocal()
        user = None
        orig_enabled, orig_exchange = server.GITHUB_OAUTH_ENABLED, server._github_exchange_claims
        try:
            server.GITHUB_OAUTH_ENABLED = True
            user = make_user(db, AccountLevel.trial)
            user.email_verified = True
            db.commit()
            old_hash = user.password_hash
            sub = f"github-sub-{_sec.token_hex(4)}"
            server._github_exchange_claims = AsyncMock(return_value=_claims(user.email, sub))

            state = _start_github_flow()
            r = client.get(f"/auth/github/callback?code=abc&state={state}", follow_redirects=False)
            assert r.status_code == 303

            db.refresh(user)
            assert user.github_id == sub
            assert user.password_hash == old_hash
            assert verify_password("testpass123", user.password_hash)
        finally:
            server.GITHUB_OAUTH_ENABLED, server._github_exchange_claims = orig_enabled, orig_exchange
            cleanup(db, user); db.close()

    def test_matching_unverified_email_links_and_invalidates_old_password():
        db = SessionLocal()
        user = None
        orig_enabled, orig_exchange = server.GITHUB_OAUTH_ENABLED, server._github_exchange_claims
        try:
            server.GITHUB_OAUTH_ENABLED = True
            user = make_user(db, AccountLevel.trial)  # email_verified defaults to False
            assert user.email_verified is False
            sub = f"github-sub-{_sec.token_hex(4)}"
            server._github_exchange_claims = AsyncMock(return_value=_claims(user.email, sub))

            state = _start_github_flow()
            r = client.get(f"/auth/github/callback?code=abc&state={state}", follow_redirects=False)
            assert r.status_code == 303

            db.refresh(user)
            assert user.github_id == sub
            assert user.email_verified is True
            assert not verify_password("testpass123", user.password_hash)
        finally:
            server.GITHUB_OAUTH_ENABLED, server._github_exchange_claims = orig_enabled, orig_exchange
            cleanup(db, user); db.close()

    def test_bad_state_redirects_to_login_error():
        orig_enabled = server.GITHUB_OAUTH_ENABLED
        try:
            server.GITHUB_OAUTH_ENABLED = True
            r = client.get("/auth/github/callback?code=abc&state=not-a-real-state", follow_redirects=False)
            assert r.status_code == 303
            assert "error=oauth_failed" in r.headers.get("location", "")
        finally:
            server.GITHUB_OAUTH_ENABLED = orig_enabled

    def test_cancelled_consent_redirects_to_login_error():
        orig_enabled = server.GITHUB_OAUTH_ENABLED
        try:
            server.GITHUB_OAUTH_ENABLED = True
            r = client.get("/auth/github/callback?error=access_denied", follow_redirects=False)
            assert r.status_code == 303
            assert "error=oauth_failed" in r.headers.get("location", "")
        finally:
            server.GITHUB_OAUTH_ENABLED = orig_enabled

    def test_private_email_with_no_verified_primary_fails_login():
        # Exercises the real _github_exchange_claims (not the mocked shortcut used above) by
        # stubbing the two httpx calls it makes: token exchange, then /user (email absent —
        # kept private), then /user/emails with no verified primary. Should surface as a
        # generic oauth_failed rather than creating an unverified account.
        import httpx

        class _FakeResponse:
            def __init__(self, payload):
                self._payload = payload
            def raise_for_status(self):
                pass
            def json(self):
                return self._payload

        async def _fake_post(self, url, **kwargs):
            assert url == "https://github.com/login/oauth/access_token"
            return _FakeResponse({"access_token": "fake-token"})

        async def _fake_get(self, url, **kwargs):
            if url == "https://api.github.com/user":
                return _FakeResponse({"id": 999999, "email": None, "name": "Private Person", "login": "privateperson"})
            assert url == "https://api.github.com/user/emails"
            return _FakeResponse([{"email": "private@test.internal", "primary": False, "verified": True}])

        orig_enabled = server.GITHUB_OAUTH_ENABLED
        orig_client_post, orig_client_get = httpx.AsyncClient.post, httpx.AsyncClient.get
        try:
            server.GITHUB_OAUTH_ENABLED = True
            httpx.AsyncClient.post = _fake_post
            httpx.AsyncClient.get = _fake_get

            state = _start_github_flow()
            r = client.get(f"/auth/github/callback?code=abc&state={state}", follow_redirects=False)
            assert r.status_code == 303
            assert "error=oauth_failed" in r.headers.get("location", "")
        finally:
            server.GITHUB_OAUTH_ENABLED = orig_enabled
            httpx.AsyncClient.post, httpx.AsyncClient.get = orig_client_post, orig_client_get

    test("GET /auth/github* -> 404 when GitHub OAuth is disabled",                  test_routes_404_when_disabled)
    test("GitHub callback: new email -> verified trial user + referral",            test_new_email_creates_verified_trial_user_and_consumes_referral)
    test("GitHub callback: same sub twice -> logs into same user, no duplicate",     test_same_sub_logs_into_same_user_no_duplicate)
    test("GitHub callback: verified existing email -> links, password kept",        test_matching_verified_email_links_without_touching_password)
    test("GitHub callback: unverified existing email -> links, old password dead",  test_matching_unverified_email_links_and_invalidates_old_password)
    test("GitHub callback: unknown/expired state -> login?error=oauth_failed",       test_bad_state_redirects_to_login_error)
    test("GitHub callback: consent denied -> login?error=oauth_failed",             test_cancelled_consent_redirects_to_login_error)
    test("GitHub callback: private email with no verified primary -> oauth_failed", test_private_email_with_no_verified_primary_fails_login)
