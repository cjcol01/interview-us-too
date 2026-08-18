import secrets as _sec

from database import SessionLocal
from models import AccountLevel, User
from tests.helpers import cleanup, delete_by_name, make_cookie, make_user


def register(test, skip, client):

    # -- Public pages --------------------------------------------------------

    def test_landing_200():
        assert client.get("/").status_code == 200

    def test_login_page_200():
        assert client.get("/login").status_code == 200

    def test_pricing_accessible_without_auth():
        """Pricing is a public page — it only redirects away already-unlimited users."""
        r = client.get("/pricing", follow_redirects=False)
        assert r.status_code == 200

    # -- Auth: unauthenticated redirects -------------------------------------

    def test_app_redirects_to_login():
        r = client.get("/app", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "login" in r.headers.get("location", "")

    def test_settings_requires_auth():
        r = client.get("/settings", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "login" in r.headers.get("location", "")

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

    def test_password_complexity_rules():
        """Unit-level check of the shared validator (avoids the register rate-limit
        cooldown, which would otherwise fire on back-to-back /auth/register calls)."""
        from auth import validate_password
        assert validate_password("alllowercase1!") is not None   # missing uppercase
        assert validate_password("ALLUPPERCASE1!") is not None   # missing lowercase
        assert validate_password("NoNumberHere!") is not None    # missing number
        assert validate_password("NoSymbolHere1") is not None    # missing symbol
        assert validate_password("StrongPass123!") is None

    def test_register_rejects_password_missing_symbol():
        r = client.post("/auth/register", json={
            "full_name": "Test", "username": f"_reg_pw_{_sec.token_hex(4)}",
            "email": f"_reg_pw_{_sec.token_hex(4)}@test.internal", "password": "NoSymbolHere1",
        })
        assert r.status_code == 400

    def test_register_accepts_strong_password():
        uname = f"_reg_pw_strong_{_sec.token_hex(4)}"
        try:
            r = client.post("/auth/register", json={
                "full_name": "Test", "username": uname,
                "email": f"{uname}@test.internal", "password": "StrongPass123!",
            })
            assert r.status_code == 200, r.text
        finally:
            delete_by_name(uname)

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

    def test_settings_shows_session_warning_for_paid_users():
        """Paid (session-based) users see the session-start reminder toggle in
        the Hotkeys section so they can control the pre-capture warning modal."""
        token, uname = make_cookie(AccountLevel.paid)
        try:
            r = client.get("/settings", cookies={"session": token})
            assert r.status_code == 200
            assert "session-warning-toggle" in r.text
            assert "Session start reminder" in r.text
        finally:
            delete_by_name(uname)

    def test_settings_hides_session_warning_for_unlimited_users():
        token, uname = make_cookie(AccountLevel.unlimited)
        try:
            r = client.get("/settings", cookies={"session": token})
            assert r.status_code == 200
            assert "session-notice" not in r.text
        finally:
            delete_by_name(uname)

    def test_settings_hides_session_warning_for_trial_users():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/settings", cookies={"session": token})
            assert r.status_code == 200
            assert "session-notice" not in r.text
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
            assert "complexity" in r.json()
        finally:
            delete_by_name(uname)

    def test_complexity_up_clamps_at_max():
        from server import COMPLEXITY_MAX

        token, uname = make_cookie(AccountLevel.trial)
        try:
            for _ in range(COMPLEXITY_MAX + 3):
                r = client.post("/settings/complexity/up", cookies={"session": token})
                assert r.status_code == 200
            assert r.json()["complexity"] == COMPLEXITY_MAX
        finally:
            delete_by_name(uname)

    def test_complexity_down_clamps_at_min():
        from server import COMPLEXITY_MIN

        token, uname = make_cookie(AccountLevel.trial)
        try:
            for _ in range(COMPLEXITY_MIN + 3):
                r = client.post("/settings/complexity/down", cookies={"session": token})
                assert r.status_code == 200
            assert r.json()["complexity"] == COMPLEXITY_MIN
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

    # -- GET /auth/logout (new variant added in login refresh) -----------------

    def test_get_logout_redirects():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/auth/logout", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "login" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    # -- /onboarding ----------------------------------------------------------

    def test_onboarding_renders_for_trial_user():
        token, uname = make_cookie(AccountLevel.trial)
        db = SessionLocal()
        try:
            from models import User
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            db.commit()
            r = client.get("/onboarding", cookies={"session": token})
            assert r.status_code == 200
            assert u.api_token in r.text
        finally:
            db.close()
            delete_by_name(uname)

    def test_onboarding_generates_api_token_if_missing():
        from models import User
        token, uname = make_cookie(AccountLevel.trial)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.api_token = None
            u.email_verified = True
            db.commit()
            r = client.get("/onboarding", cookies={"session": token})
            assert r.status_code == 200
            db.refresh(u)
            assert u.api_token is not None and len(u.api_token) > 0
        finally:
            db.close()
            delete_by_name(uname)

    def test_onboarding_accessible_for_non_trial_users():
        """Paid/unlimited users can revisit the setup guide — the trial-only gate
        was removed so they can reconnect the extension on a new device."""
        from models import User
        token, uname = make_cookie(AccountLevel.paid)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            db.commit()
            r = client.get("/onboarding", cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 200
        finally:
            db.close()
            delete_by_name(uname)

    # -- /welcome ---------------------------------------------------------------

    def test_welcome_renders_for_trial_user():
        token, uname = make_cookie(AccountLevel.trial)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            db.commit()
            r = client.get("/welcome", cookies={"session": token})
            assert r.status_code == 200
        finally:
            db.close()
            delete_by_name(uname)

    def test_welcome_redirects_non_trial_to_app():
        token, uname = make_cookie(AccountLevel.paid)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            db.commit()
            r = client.get("/welcome", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/app" in r.headers.get("location", "")
        finally:
            db.close()
            delete_by_name(uname)

    def test_welcome_redirects_unverified_to_verify_pending():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/welcome", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "verify-pending" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    # -- /welcome/next (universal register page) --------------------------------

    def test_welcome_next_renders_for_anon():
        """Anonymous visitors get the register form."""
        r = client.get("/welcome/next")
        assert r.status_code == 200
        # welcome_next_anon.html contains the register form
        assert "register" in r.text.lower() or "password" in r.text.lower()

    def test_welcome_next_authenticated_redirects_to_app():
        """Verified authenticated users are redirected to /app (or validated next)."""
        token, uname = make_cookie(AccountLevel.paid)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            db.commit()
            r = client.get("/welcome/next", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/app" in r.headers.get("location", "")
        finally:
            db.close()
            delete_by_name(uname)

    def test_welcome_next_authenticated_honours_safe_next():
        """Validated relative next= is used as the redirect destination."""
        token, uname = make_cookie(AccountLevel.paid)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            db.commit()
            r = client.get("/welcome/next?next=/pricing", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/pricing" in r.headers.get("location", "")
        finally:
            db.close()
            delete_by_name(uname)

    def test_welcome_next_rejects_absolute_next():
        """Absolute or protocol-relative next= values are ignored (open-redirect guard)."""
        token, uname = make_cookie(AccountLevel.paid)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            db.commit()
            for bad in ("https://evil.com", "//evil.com"):
                r = client.get(
                    f"/welcome/next?next={bad}",
                    cookies={"session": token},
                    follow_redirects=False,
                )
                loc = r.headers.get("location", "")
                assert "evil.com" not in loc, f"open redirect for next={bad!r}: {loc!r}"
        finally:
            db.close()
            delete_by_name(uname)

    def test_welcome_next_redirects_unverified_to_verify_pending():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/welcome/next", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "verify-pending" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    def test_register_persists_interview_date():
        """interview_date supplied at register is saved on the new User."""
        import secrets as _s
        uname = "test_reg_date_" + _s.token_hex(4)
        db = SessionLocal()
        try:
            r = client.post("/auth/register", json={
                "username": uname,
                "full_name": "Test User",
                "email": f"{uname}@example.com",
                "password": "Passw0rd!",
                "interview_date": "2099-03-15",
            })
            assert r.status_code == 200, r.text
            u = db.query(User).filter(User.username == uname).first()
            assert u is not None
            assert u.interview_date is not None
            assert u.interview_date.isoformat() == "2099-03-15"
        finally:
            db.close()
            delete_by_name(uname)

    def test_register_ignores_malformed_interview_date():
        """A bad date string never blocks registration — it's silently ignored."""
        import secrets as _s
        uname = "test_reg_baddate_" + _s.token_hex(4)
        db = SessionLocal()
        try:
            r = client.post("/auth/register", json={
                "username": uname,
                "full_name": "Test User",
                "email": f"{uname}@example.com",
                "password": "Passw0rd!",
                "interview_date": "not-a-date",
            })
            assert r.status_code == 200, r.text
            u = db.query(User).filter(User.username == uname).first()
            assert u is not None
            assert u.interview_date is None
        finally:
            db.close()
            delete_by_name(uname)

    # -- Interview reminder scheduler -------------------------------------------

    def test_send_due_interview_reminders_sends_and_marks_sent():
        import server as srv
        from datetime import datetime, timedelta
        from unittest.mock import patch
        db = SessionLocal()
        tag = _sec.token_hex(4)
        uname = f"_remind_{tag}"
        try:
            u = User(
                username=uname, email=f"{uname}@test.internal",
                full_name="Remind Me", password_hash="x",
                account_level=AccountLevel.trial,
                email_verified=True,
                interview_date=(datetime.utcnow() + timedelta(days=1)).date(),
                interview_reminder_sent=False,
            )
            db.add(u); db.commit()
            with patch("server.send_interview_reminder_email") as sent:
                count = srv._send_due_interview_reminders()
            assert count >= 1
            sent.assert_any_call(u.email, "Remind Me")
            db.refresh(u)
            assert u.interview_reminder_sent is True
        finally:
            db.close()
            delete_by_name(uname)

    def test_send_due_interview_reminders_skips_already_sent():
        import server as srv
        from datetime import datetime, timedelta
        from unittest.mock import patch
        db = SessionLocal()
        tag = _sec.token_hex(4)
        uname = f"_remind_{tag}"
        try:
            u = User(
                username=uname, email=f"{uname}@test.internal",
                full_name="Already Sent", password_hash="x",
                account_level=AccountLevel.trial,
                email_verified=True,
                interview_date=(datetime.utcnow() + timedelta(days=1)).date(),
                interview_reminder_sent=True,
            )
            db.add(u); db.commit()
            with patch("server.send_interview_reminder_email") as sent:
                srv._send_due_interview_reminders()
            sent.assert_not_called()
        finally:
            db.close()
            delete_by_name(uname)

    # -- /verify-pending ------------------------------------------------------

    def test_verify_pending_renders_for_unverified():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/verify-pending", cookies={"session": token})
            assert r.status_code == 200
        finally:
            delete_by_name(uname)

    def test_verify_pending_redirects_verified_user():
        from models import User
        token, uname = make_cookie(AccountLevel.trial)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            u.setup_complete = True
            db.commit()
            r = client.get("/verify-pending", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/app" in r.headers.get("location", "")
        finally:
            db.close()
            delete_by_name(uname)

    # -- /auth/resend-verification --------------------------------------------

    def test_resend_verification_ok_for_unverified():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.post("/auth/resend-verification", cookies={"session": token})
            # Resend may fail silently (placeholder key) but the route returns 200
            assert r.status_code == 200
        finally:
            delete_by_name(uname)

    def test_resend_verification_400_for_already_verified():
        from models import User
        token, uname = make_cookie(AccountLevel.trial)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            db.commit()
            r = client.post("/auth/resend-verification", cookies={"session": token})
            assert r.status_code == 400
        finally:
            db.close()
            delete_by_name(uname)

    # -- /api/me happy path ---------------------------------------------------

    def test_api_me_returns_account_level_and_hotkeys():
        from auth import create_token
        from database import SessionLocal as SL
        from models import User
        token, uname = make_cookie(AccountLevel.trial)
        db = SL()
        try:
            u = db.query(User).filter(User.username == uname).first()
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
            body = r.json()
            assert body["account_level"] == AccountLevel.trial.value
            assert "hotkeys" in body
            assert "capture" in body["hotkeys"]
        finally:
            db.close()
            delete_by_name(uname)

    test("Landing page returns 200",                           test_landing_200)
    test("Login page returns 200",                             test_login_page_200)
    test("/pricing accessible without auth",                   test_pricing_accessible_without_auth)
    test("Unauthenticated /app redirects to login",            test_app_redirects_to_login)
    test("/settings requires auth",                            test_settings_requires_auth)
    test("/billing/success requires auth",                     test_billing_success_requires_auth)
    test("/trial-end requires auth",                           test_trial_end_requires_auth)
    test("Login rejects wrong credentials",                    test_login_rejects_wrong_credentials)
    test("Login rejects missing fields (422)",                 test_login_rejects_missing_fields)
    test("Register rejects short password",                    test_register_rejects_short_password)
    test("Password complexity validator rules",                 test_password_complexity_rules)
    test("Register rejects password missing symbol",           test_register_rejects_password_missing_symbol)
    test("Register accepts strong password",                   test_register_accepts_strong_password)
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
    test("/settings shows session-start warning for paid users",     test_settings_shows_session_warning_for_paid_users)
    test("/settings hides session-start warning for unlimited users", test_settings_hides_session_warning_for_unlimited_users)
    test("/settings hides session-start warning for trial users",     test_settings_hides_session_warning_for_trial_users)
    test("/pricing accessible when authenticated",             test_pricing_page_accessible_when_authed)
    test("Complexity: unknown direction is handled",           test_complexity_endpoint_handles_unknown_direction)
    test("Complexity: up increments setting",                  test_complexity_up_increments)
    test("Complexity: up clamps at COMPLEXITY_MAX",             test_complexity_up_clamps_at_max)
    test("Complexity: down clamps at COMPLEXITY_MIN",           test_complexity_down_clamps_at_min)
    test("Token regenerate returns new token",                 test_token_regenerate_returns_new_token)
    test("Logout clears session cookie",                       test_logout_clears_session)
    test("GET /auth/logout also redirects to login",          test_get_logout_redirects)
    test("/onboarding renders for trial user",                test_onboarding_renders_for_trial_user)
    test("/onboarding generates api_token if missing",        test_onboarding_generates_api_token_if_missing)
    test("/onboarding accessible for non-trial users",        test_onboarding_accessible_for_non_trial_users)
    test("/welcome renders for trial user",                   test_welcome_renders_for_trial_user)
    test("/welcome redirects non-trial to /app",               test_welcome_redirects_non_trial_to_app)
    test("/welcome redirects unverified to /verify-pending",   test_welcome_redirects_unverified_to_verify_pending)
    test("/welcome/next renders register form for anon",         test_welcome_next_renders_for_anon)
    test("/welcome/next auth → redirects to /app",               test_welcome_next_authenticated_redirects_to_app)
    test("/welcome/next auth + safe next → honours next",        test_welcome_next_authenticated_honours_safe_next)
    test("/welcome/next rejects absolute next (open-redirect)",  test_welcome_next_rejects_absolute_next)
    test("/welcome/next redirects unverified to /verify-pending", test_welcome_next_redirects_unverified_to_verify_pending)
    test("Register persists interview_date",                     test_register_persists_interview_date)
    test("Register ignores malformed interview_date",            test_register_ignores_malformed_interview_date)
    test("_send_due_interview_reminders sends + marks sent",   test_send_due_interview_reminders_sends_and_marks_sent)
    test("_send_due_interview_reminders skips already-sent",   test_send_due_interview_reminders_skips_already_sent)
    test("/verify-pending renders for unverified user",       test_verify_pending_renders_for_unverified)
    test("/verify-pending redirects verified user to /app",   test_verify_pending_redirects_verified_user)
    test("Resend verification ok for unverified user",        test_resend_verification_ok_for_unverified)
    test("Resend verification 400 for already verified",      test_resend_verification_400_for_already_verified)
    test("/api/me returns account_level + hotkeys",           test_api_me_returns_account_level_and_hotkeys)

    # -- GET /verify (email verification) ------------------------------------

    def test_verify_valid_token_sets_verified_and_redirects():
        import secrets as sec
        from auth import hash_password
        db = SessionLocal()
        tag = sec.token_hex(4)
        uname = f"_verify_{tag}"
        verify_tok = sec.token_urlsafe(32)
        try:
            u = User(
                username=uname, email=f"{uname}@test.internal",
                full_name="V", password_hash=hash_password("pass12345"),
                account_level=AccountLevel.trial,
                verify_token=verify_tok,
            )
            db.add(u); db.commit()
            r = client.get(f"/verify?token={verify_tok}", follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            db.refresh(u)
            assert u.email_verified is True
            assert u.verify_token is None
        finally:
            db.query(User).filter(User.username == uname).delete()
            db.commit(); db.close()

    def test_verify_spent_token_redirects_to_login():
        # A spent token (double-click, or an email client prefetching the link) is by far the
        # likeliest reason for a miss here, and it used to 400 with a bare error page. It now
        # lands on /login with an explanation that holds whether the link was spent or bogus.
        r = client.get("/verify?token=notarealtoken", follow_redirects=False)
        assert r.status_code in (302, 303, 307), r.status_code
        assert "/login?error=verify_link_used" in r.headers["location"], r.headers["location"]

    def test_verify_valid_token_signs_the_clicking_device_in():
        # The device holding the email is often not the one that signed up, so /verify has to
        # issue a session itself — otherwise its destination bounces to a bare /login.
        import secrets as sec
        from auth import hash_password
        db = SessionLocal()
        tag = sec.token_hex(4)
        uname = f"_verifycookie_{tag}"
        verify_tok = sec.token_urlsafe(32)
        try:
            u = User(
                username=uname, email=f"{uname}@test.internal",
                full_name="V", password_hash=hash_password("pass12345"),
                account_level=AccountLevel.trial,
                verify_token=verify_tok,
            )
            db.add(u); db.commit()
            r = client.get(f"/verify?token={verify_tok}", follow_redirects=False)
            assert "session" in r.cookies, dict(r.cookies)
            # And that session must actually work — a cookie that doesn't authenticate would
            # land them right back on /login, which is the whole bug this closes.
            status = client.get("/api/verify-status", cookies={"session": r.cookies["session"]})
            assert status.status_code == 200, status.status_code
            assert status.json()["verified"] is True, status.json()
        finally:
            db.query(User).filter(User.username == uname).delete()
            db.commit(); db.close()

    test("GET /verify: valid token marks verified + redirects",  test_verify_valid_token_sets_verified_and_redirects)
    test("GET /verify: spent/invalid token → /login notice",     test_verify_spent_token_redirects_to_login)
    test("GET /verify: signs in the device that clicked",        test_verify_valid_token_signs_the_clicking_device_in)

    # -- GET /app redirect logic ---------------------------------------------

    def test_app_redirects_unverified_to_verify_pending():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/app", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "verify-pending" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    def test_app_redirects_free_to_pricing():
        token, uname = make_cookie(AccountLevel.free)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            db.commit()
            r = client.get("/app", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/pricing" in r.headers.get("location", "")
        finally:
            db.close(); delete_by_name(uname)

    def test_app_redirects_trial_no_welcome_to_welcome():
        token, uname = make_cookie(AccountLevel.trial)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            u.welcome_seen = False
            db.commit()
            r = client.get("/app", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/welcome" in r.headers.get("location", "")
        finally:
            db.close(); delete_by_name(uname)

    def test_app_redirects_trial_no_setup_to_onboarding():
        token, uname = make_cookie(AccountLevel.trial)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            u.welcome_seen = True
            u.setup_complete = False
            db.commit()
            r = client.get("/app", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/onboarding" in r.headers.get("location", "")
        finally:
            db.close(); delete_by_name(uname)

    def test_onboarding_visit_marks_welcome_seen():
        token, uname = make_cookie(AccountLevel.trial)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.email_verified = True
            u.welcome_seen = False
            db.commit()
            r = client.get("/onboarding", cookies={"session": token})
            assert r.status_code == 200
            db.refresh(u)
            assert u.welcome_seen is True
        finally:
            db.close(); delete_by_name(uname)

    test("GET /app: unverified user → /verify-pending",           test_app_redirects_unverified_to_verify_pending)
    test("GET /app: free user → /pricing",                        test_app_redirects_free_to_pricing)
    test("GET /app: trial, welcome not seen → /welcome",          test_app_redirects_trial_no_welcome_to_welcome)
    test("GET /app: trial without setup → /onboarding",           test_app_redirects_trial_no_setup_to_onboarding)
    test("GET /onboarding: marks welcome_seen",                   test_onboarding_visit_marks_welcome_seen)

    # -- POST /api/notify/disabled and /api/notify/enabled ------------------

    def test_notify_disabled_free_user_is_noop():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.free)
            r = client.post("/api/notify/disabled",
                            headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
        finally:
            cleanup(db, u); db.close()

    def test_notify_disabled_requires_bearer():
        r = client.post("/api/notify/disabled")
        assert r.status_code in (401, 403)

    def test_notify_enabled_free_user_is_noop():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.free)
            r = client.post("/api/notify/enabled",
                            headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
        finally:
            cleanup(db, u); db.close()

    def test_notify_enabled_unlimited_user_is_noop():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.unlimited)
            r = client.post("/api/notify/enabled",
                            headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
        finally:
            cleanup(db, u); db.close()

    def test_notify_enabled_trial_user_returns_200():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.post("/api/notify/enabled",
                            headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
        finally:
            cleanup(db, u); db.close()

    test("POST /api/notify/disabled: free user no-op → 200",      test_notify_disabled_free_user_is_noop)
    test("POST /api/notify/disabled requires Bearer token",        test_notify_disabled_requires_bearer)
    test("POST /api/notify/enabled: free user no-op → 200",       test_notify_enabled_free_user_is_noop)
    test("POST /api/notify/enabled: unlimited user no-op → 200",  test_notify_enabled_unlimited_user_is_noop)
    test("POST /api/notify/enabled: trial user → 200",            test_notify_enabled_trial_user_returns_200)

    # -- GET /api/billing/status ---------------------------------------------

    def test_billing_status_returns_expected_fields():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/api/billing/status", cookies={"session": token})
            assert r.status_code == 200
            body = r.json()
            assert "account_level" in body
            assert "sessions_remaining" in body
            assert "intro_declined" in body
            assert body["account_level"] == AccountLevel.trial.value
        finally:
            delete_by_name(uname)

    def test_billing_status_requires_auth():
        r = client.get("/api/billing/status", follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    test("GET /api/billing/status returns account fields",         test_billing_status_returns_expected_fields)
    test("GET /api/billing/status requires auth",                  test_billing_status_requires_auth)

    # -- POST /billing/offer -------------------------------------------------

    def test_billing_offer_requires_auth():
        r = client.post("/billing/offer", follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    def test_billing_offer_redirects_to_settings():
        token, uname = make_cookie(AccountLevel.unlimited)
        try:
            r = client.post("/billing/offer", cookies={"session": token},
                            follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "offer=claimed" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    test("POST /billing/offer requires auth",                      test_billing_offer_requires_auth)
    test("POST /billing/offer redirects to /settings?offer=claimed", test_billing_offer_redirects_to_settings)

    # -- POST /billing/feedback ----------------------------------------------

    def test_billing_feedback_requires_auth():
        r = client.post("/billing/feedback",
                        data={"reason": "", "detail": ""},
                        follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    def test_billing_feedback_redirects_to_settings():
        token, uname = make_cookie(AccountLevel.unlimited)
        try:
            r = client.post("/billing/feedback",
                            data={"reason": "keeping it", "detail": ""},
                            cookies={"session": token},
                            follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/settings" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    test("POST /billing/feedback requires auth",                   test_billing_feedback_requires_auth)
    test("POST /billing/feedback redirects to /settings",          test_billing_feedback_redirects_to_settings)

    # -- GET /screenshot -------------------------------------------------------

    def test_screenshot_blocked_for_free_user():
        token, uname = make_cookie(AccountLevel.free)
        try:
            r = client.get("/screenshot", cookies={"session": token})
            assert r.status_code == 403
        finally:
            delete_by_name(uname)

    def test_screenshot_404_when_none_taken():
        from auth import create_token
        from server import SCREENSHOTS_DIR
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            # A prior test run's leftover screenshot file for a reused (autoincrement)
            # user id would otherwise make this a false 200 — clear it defensively.
            leftover = SCREENSHOTS_DIR / f"{u.id}.png"
            leftover.unlink(missing_ok=True)
            r = client.get("/screenshot", cookies={"session": token})
            assert r.status_code == 404
        finally:
            cleanup(db, u)
            db.close()

    test("GET /screenshot blocked for free user (403)",             test_screenshot_blocked_for_free_user)
    test("GET /screenshot: 404 when none taken yet",                test_screenshot_404_when_none_taken)

    # -- Misc public pages -------------------------------------------------------

    def test_partner_page_200():
        assert client.get("/partner").status_code == 200

    def test_faq_page_200():
        assert client.get("/faq").status_code == 200

    def test_forgot_password_page_200():
        assert client.get("/forgot-password").status_code == 200

    def test_reset_password_page_200():
        assert client.get("/reset-password?token=notarealtoken").status_code == 200

    test("/partner page returns 200",                               test_partner_page_200)
    test("/faq page returns 200",                                   test_faq_page_200)
    test("/forgot-password page returns 200",                       test_forgot_password_page_200)
    test("/reset-password page returns 200",                        test_reset_password_page_200)
