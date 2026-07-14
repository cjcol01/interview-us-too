def register(test, skip, client):
    from auth import create_token
    from database import SessionLocal
    from models import AccountLevel
    from tests.helpers import cleanup, make_user

    def test_mobile_link_returns_url_with_token():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post("/api/onboarding/mobile-link", cookies={"session": token})
            assert r.status_code == 200
            assert "url" in r.json()
            assert "token=" in r.json()["url"]
        finally:
            cleanup(db, u); db.close()

    def test_mobile_link_requires_auth():
        r = client.post("/api/onboarding/mobile-link")
        assert r.status_code == 401

    def test_mobile_login_valid_token_sets_session():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            session_token = create_token(u.id)
            link_resp = client.post("/api/onboarding/mobile-link", cookies={"session": session_token})
            mobile_token = link_resp.json()["url"].split("token=")[-1]

            r = client.get(f"/mobile-login?token={mobile_token}", follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/app" in r.headers.get("location", "")
            assert "session" in r.cookies
        finally:
            cleanup(db, u); db.close()

    def test_mobile_login_missing_token_redirects_to_login_error():
        r = client.get("/mobile-login?token=notarealtoken", follow_redirects=False)
        assert r.status_code in (302, 303, 307)
        assert "link_expired" in r.headers.get("location", "")

    def test_mobile_login_deleted_user_redirects_to_login_error():
        import asyncio
        import server
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            user_id = u.id
            mobile_token = "test_mobile_deleted_user_token"
            asyncio.run(server.app.state.redis.setex(f"mobile_login:{mobile_token}", 300, str(user_id)))
            cleanup(db, u)  # deletes the user, token remains in redis
            u = None

            r = client.get(f"/mobile-login?token={mobile_token}", follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "link_expired" in r.headers.get("location", "")
        finally:
            if u is not None:
                cleanup(db, u)
            db.close()

    test("POST /api/onboarding/mobile-link returns url with token", test_mobile_link_returns_url_with_token)
    test("POST /api/onboarding/mobile-link requires auth",          test_mobile_link_requires_auth)
    test("GET /mobile-login: valid token sets session + redirects", test_mobile_login_valid_token_sets_session)
    test("GET /mobile-login: missing token -> login?error",         test_mobile_login_missing_token_redirects_to_login_error)
    test("GET /mobile-login: deleted user -> login?error",          test_mobile_login_deleted_user_redirects_to_login_error)
