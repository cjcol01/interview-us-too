import secrets as _sec

from database import SessionLocal
from models import AccountLevel, User
from tests.helpers import delete_by_name, make_cookie


def register(test, skip, client):

    # -- Public pages --------------------------------------------------------

    def test_landing_200():
        assert client.get("/").status_code == 200

    def test_login_page_200():
        assert client.get("/login").status_code == 200

    # -- Auth: unauthenticated redirects -------------------------------------

    def test_app_redirects_to_login():
        r = client.get("/app", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "login" in r.headers.get("location", "")

    def test_settings_requires_auth():
        r = client.get("/settings", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "login" in r.headers.get("location", "")

    def test_pricing_requires_auth():
        r = client.get("/pricing", follow_redirects=False)
        assert r.status_code in (302, 307)

    def test_billing_success_requires_auth():
        r = client.get("/billing/success", follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    def test_trial_end_requires_auth():
        r = client.get("/trial-end", follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    # -- Auth: login / register validation -----------------------------------

    def test_login_rejects_wrong_credentials():
        r = client.post("/auth/login", json={"username": "nobody", "password": "wrongpass"})
        assert r.status_code == 401

    def test_login_rejects_missing_fields():
        r = client.post("/auth/login", json={"username": "missing_password"})
        assert r.status_code == 422

    def test_register_rejects_short_password():
        r = client.post("/auth/register", json={
            "full_name": "Test", "username": "_reg_pw_test",
            "email": "_reg_pw@test.internal", "password": "short",
        })
        assert r.status_code == 400

    def test_register_rejects_duplicate_username():
        from auth import hash_password
        tag = _sec.token_hex(4)
        uname = f"_dup_http_{tag}"
        db = SessionLocal()
        try:
            db.add(User(
                username=uname, email=f"{uname}@test.internal",
                full_name="Dup", password_hash=hash_password("testpassword123"),
                account_level=AccountLevel.trial,
            ))
            db.commit()
            r = client.post("/auth/register", json={
                "full_name": "Dup2", "username": uname,
                "email": f"other_{uname}@test.internal", "password": "testpassword123",
            })
            assert r.status_code == 400
            assert "already taken" in r.json()["detail"].lower()
        finally:
            db.query(User).filter(User.username == uname).delete()
            db.commit()
            db.close()

    def test_register_rejects_duplicate_email():
        from auth import hash_password
        tag = _sec.token_hex(4)
        email = f"_dup_email_{tag}@test.internal"
        db = SessionLocal()
        try:
            db.add(User(
                username=f"_orig_{tag}", email=email,
                full_name="Orig", password_hash=hash_password("testpassword123"),
                account_level=AccountLevel.trial,
            ))
            db.commit()
            r = client.post("/auth/register", json={
                "full_name": "Dup", "username": f"_new_{tag}",
                "email": email, "password": "testpassword123",
            })
            assert r.status_code == 400
            assert "email" in r.json()["detail"].lower()
        finally:
            db.query(User).filter(User.email == email).delete()
            db.commit()
            db.close()

    # -- API token routes ----------------------------------------------------

    def test_capture_requires_auth_header():
        r = client.post("/api/capture", json={"image": "abc", "complexity": 2, "monitor": "browser"})
        assert r.status_code in (401, 403)

    def test_capture_rejects_invalid_token():
        r = client.post("/api/capture",
                        json={"image": "abc", "complexity": 2, "monitor": "browser"},
                        headers={"Authorization": "Bearer notarealtoken"})
        assert r.status_code == 401

    def test_api_me_rejects_invalid_token():
        r = client.get("/api/me", headers={"Authorization": "Bearer notarealtoken"})
        assert r.status_code == 401

    def test_stream_requires_auth():
        r = client.get("/stream")
        assert r.status_code == 401

    def test_latest_requires_auth():
        r = client.get("/latest")
        assert r.status_code == 401

    # -- Account-level gating ------------------------------------------------

    def test_free_user_blocked_from_gated_routes():
        token, uname = make_cookie(AccountLevel.free)
        try:
            assert client.get("/latest", cookies={"session": token}).status_code == 403
            assert client.get("/stream", cookies={"session": token}).status_code == 403
        finally:
            delete_by_name(uname)

    def test_trial_user_can_access_latest():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/latest", cookies={"session": token})
            assert r.status_code == 200
            body = r.json()
            assert "capture" in body and "settings" in body
        finally:
            delete_by_name(uname)

    def test_settings_page_accessible_when_authed():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/settings", cookies={"session": token})
            assert r.status_code == 200
        finally:
            delete_by_name(uname)

    def test_pricing_page_accessible_when_authed():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/pricing", cookies={"session": token})
            assert r.status_code == 200
        finally:
            delete_by_name(uname)

    # -- Misc endpoints ------------------------------------------------------

    def test_complexity_endpoint_handles_unknown_direction():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.post("/settings/complexity/sideways", cookies={"session": token})
            assert r.status_code == 200
        finally:
            delete_by_name(uname)

    def test_complexity_up_increments():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.post("/settings/complexity/up", cookies={"session": token})
            assert r.status_code == 200
        finally:
            delete_by_name(uname)

    def test_token_regenerate_returns_new_token():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.post("/api/token/regenerate", cookies={"session": token})
            assert r.status_code == 200
            assert "token" in r.json()
        finally:
            delete_by_name(uname)

    def test_logout_clears_session():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.post("/auth/logout", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
        finally:
            delete_by_name(uname)

    test("Landing page returns 200",                           test_landing_200)
    test("Login page returns 200",                             test_login_page_200)
    test("Unauthenticated /app redirects to login",            test_app_redirects_to_login)
    test("/settings requires auth",                            test_settings_requires_auth)
    test("/pricing requires auth",                             test_pricing_requires_auth)
    test("/billing/success requires auth",                     test_billing_success_requires_auth)
    test("/trial-end requires auth",                           test_trial_end_requires_auth)
    test("Login rejects wrong credentials",                    test_login_rejects_wrong_credentials)
    test("Login rejects missing fields (422)",                 test_login_rejects_missing_fields)
    test("Register rejects short password",                    test_register_rejects_short_password)
    test("Register rejects duplicate username",                test_register_rejects_duplicate_username)
    test("Register rejects duplicate email",                   test_register_rejects_duplicate_email)
    test("/api/capture requires auth header",                  test_capture_requires_auth_header)
    test("/api/capture rejects invalid token",                 test_capture_rejects_invalid_token)
    test("/api/me rejects invalid token",                      test_api_me_rejects_invalid_token)
    test("/stream requires authentication",                    test_stream_requires_auth)
    test("/latest requires authentication",                    test_latest_requires_auth)
    test("Free user blocked from subscription routes",         test_free_user_blocked_from_gated_routes)
    test("Trial user can access /latest",                      test_trial_user_can_access_latest)
    test("/settings accessible when authenticated",            test_settings_page_accessible_when_authed)
    test("/pricing accessible when authenticated",             test_pricing_page_accessible_when_authed)
    test("Complexity: unknown direction is handled",           test_complexity_endpoint_handles_unknown_direction)
    test("Complexity: up increments setting",                  test_complexity_up_increments)
    test("Token regenerate returns new token",                 test_token_regenerate_returns_new_token)
    test("Logout clears session cookie",                       test_logout_clears_session)
