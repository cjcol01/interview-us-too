def register(test, skip, client=None):

    def test_password_hashing():
        from auth import hash_password, verify_password
        hashed = hash_password("mysecretpassword")
        assert verify_password("mysecretpassword", hashed)
        assert not verify_password("wrongpassword", hashed)

    def test_token_roundtrip():
        from auth import create_token
        from config import SECRET_KEY
        from jose import jwt
        token = create_token(user_id=42)
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        assert int(payload["sub"]) == 42

    def test_duplicate_username_rejected():
        from auth import hash_password
        from database import SessionLocal, init_db
        from models import AccountLevel, User
        from sqlalchemy.exc import IntegrityError
        init_db()
        db = SessionLocal()
        try:
            for _ in range(2):
                db.add(User(
                    username="_dup_auth_test", email="_dup_auth@test.internal",
                    full_name="Dup", password_hash=hash_password("pass"),
                    account_level=AccountLevel.trial,
                ))
            db.commit()
            return False
        except IntegrityError:
            db.rollback()
            return True
        finally:
            u = db.query(User).filter(User.username == "_dup_auth_test").first()
            if u:
                db.delete(u)
                db.commit()
            db.close()

    def test_referral_code_generation():
        from auth import generate_unique_referral_code
        from database import SessionLocal, init_db
        init_db()
        db = SessionLocal()
        try:
            codes = {generate_unique_referral_code(db) for _ in range(10)}
            assert len(codes) == 10, "generated duplicate referral codes"
        finally:
            db.close()

    def test_referral_code_is_url_safe():
        from auth import generate_unique_referral_code
        from database import SessionLocal, init_db
        import urllib.parse
        init_db()
        db = SessionLocal()
        try:
            code = generate_unique_referral_code(db)
            assert code == urllib.parse.quote(code, safe=""), \
                f"referral code contains unsafe characters: {code!r}"
        finally:
            db.close()

    def test_forgot_password_unknown_email():
        """Submitting an unknown email should still return 200 (no enumeration)."""
        res = client.post("/auth/forgot-password", json={"email": "nobody@nowhere.invalid"})
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    def test_forgot_password_sets_token():
        """Submitting a known email sets reset_token + expiry on the user."""
        from auth import hash_password
        from database import SessionLocal, init_db
        from models import AccountLevel, User
        init_db()
        db = SessionLocal()
        try:
            u = User(
                username="_reset_tok_test", email="_reset_tok@test.internal",
                full_name="Reset", password_hash=hash_password("oldpass123"),
                account_level=AccountLevel.trial, email_verified=True,
            )
            db.add(u)
            db.commit()
            db.refresh(u)

            res = client.post("/auth/forgot-password", json={"email": "_reset_tok@test.internal"})
            assert res.status_code == 200

            db.expire(u)
            db.refresh(u)
            assert u.reset_token is not None
            assert u.reset_token_expiry is not None
        finally:
            u2 = db.query(User).filter(User.username == "_reset_tok_test").first()
            if u2:
                db.delete(u2)
                db.commit()
            db.close()

    def test_reset_password_valid_token():
        """A valid token lets the user set a new password and then log in with it."""
        from auth import hash_password, verify_password
        from database import SessionLocal, init_db
        from datetime import datetime, timedelta
        from models import AccountLevel, User
        import secrets
        init_db()
        db = SessionLocal()
        try:
            token = secrets.token_urlsafe(32)
            u = User(
                username="_reset_valid_test", email="_reset_valid@test.internal",
                full_name="Reset Valid", password_hash=hash_password("oldpass123"),
                account_level=AccountLevel.trial, email_verified=True,
                reset_token=token,
                reset_token_expiry=datetime.utcnow() + timedelta(hours=1),
            )
            db.add(u)
            db.commit()

            res = client.post("/auth/reset-password", json={
                "token": token,
                "new_password": "NewPass456!",
            })
            assert res.status_code == 200, res.text

            db.expire(u)
            db.refresh(u)
            assert verify_password("NewPass456!", u.password_hash)
            assert u.reset_token is None
            assert u.reset_token_expiry is None
        finally:
            u2 = db.query(User).filter(User.username == "_reset_valid_test").first()
            if u2:
                db.delete(u2)
                db.commit()
            db.close()

    def test_reset_password_expired_token():
        """An expired token is rejected with 400."""
        from auth import hash_password
        from database import SessionLocal, init_db
        from datetime import datetime, timedelta
        from models import AccountLevel, User
        import secrets
        init_db()
        db = SessionLocal()
        try:
            token = secrets.token_urlsafe(32)
            u = User(
                username="_reset_exp_test", email="_reset_exp@test.internal",
                full_name="Reset Exp", password_hash=hash_password("oldpass123"),
                account_level=AccountLevel.trial, email_verified=True,
                reset_token=token,
                reset_token_expiry=datetime.utcnow() - timedelta(minutes=1),
            )
            db.add(u)
            db.commit()

            res = client.post("/auth/reset-password", json={
                "token": token,
                "new_password": "newpass456",
            })
            assert res.status_code == 400
        finally:
            u2 = db.query(User).filter(User.username == "_reset_exp_test").first()
            if u2:
                db.delete(u2)
                db.commit()
            db.close()

    def test_reset_password_invalid_token():
        """A completely bogus token is rejected with 400."""
        res = client.post("/auth/reset-password", json={
            "token": "totallyinvalidtoken",
            "new_password": "newpass456",
        })
        assert res.status_code == 400

    def test_reset_password_too_short():
        """Password shorter than 8 chars is rejected even with a valid token."""
        from auth import hash_password
        from database import SessionLocal, init_db
        from datetime import datetime, timedelta
        from models import AccountLevel, User
        import secrets
        init_db()
        db = SessionLocal()
        try:
            token = secrets.token_urlsafe(32)
            u = User(
                username="_reset_short_test", email="_reset_short@test.internal",
                full_name="Reset Short", password_hash=hash_password("oldpass123"),
                account_level=AccountLevel.trial, email_verified=True,
                reset_token=token,
                reset_token_expiry=datetime.utcnow() + timedelta(hours=1),
            )
            db.add(u)
            db.commit()

            res = client.post("/auth/reset-password", json={
                "token": token,
                "new_password": "short",
            })
            assert res.status_code == 400
        finally:
            u2 = db.query(User).filter(User.username == "_reset_short_test").first()
            if u2:
                db.delete(u2)
                db.commit()
            db.close()

    def test_reset_token_single_use():
        """After a successful reset the token cannot be reused."""
        from auth import hash_password
        from database import SessionLocal, init_db
        from datetime import datetime, timedelta
        from models import AccountLevel, User
        import secrets
        init_db()
        db = SessionLocal()
        try:
            token = secrets.token_urlsafe(32)
            u = User(
                username="_reset_1use_test", email="_reset_1use@test.internal",
                full_name="Reset 1use", password_hash=hash_password("oldpass123"),
                account_level=AccountLevel.trial, email_verified=True,
                reset_token=token,
                reset_token_expiry=datetime.utcnow() + timedelta(hours=1),
            )
            db.add(u)
            db.commit()

            res = client.post("/auth/reset-password", json={"token": token, "new_password": "NewPass456!"})
            assert res.status_code == 200

            # Second use with the same token should fail
            res2 = client.post("/auth/reset-password", json={"token": token, "new_password": "AnotherPass789!"})
            assert res2.status_code == 400
        finally:
            u2 = db.query(User).filter(User.username == "_reset_1use_test").first()
            if u2:
                db.delete(u2)
                db.commit()
            db.close()

    def test_decode_user_id_garbage_returns_none():
        from auth import decode_user_id
        assert decode_user_id("not.a.jwt") is None

    def test_decode_user_id_expired_returns_none():
        from auth import decode_user_id
        from config import SECRET_KEY
        from datetime import datetime, timedelta
        from jose import jwt
        expired = jwt.encode(
            {"sub": "1", "exp": datetime.utcnow() - timedelta(days=1)},
            SECRET_KEY, algorithm="HS256",
        )
        assert decode_user_id(expired) is None

    def test_login_rejects_inactive_user():
        from auth import hash_password
        from database import SessionLocal, init_db
        from models import AccountLevel, User
        init_db()
        db = SessionLocal()
        try:
            u = User(
                username="_inactive_login_test", email="_inactive_login@test.internal",
                full_name="Inactive", password_hash=hash_password("testpass123"),
                account_level=AccountLevel.trial, is_active=False,
            )
            db.add(u)
            db.commit()
            res = client.post("/auth/login", json={"username": "_inactive_login_test", "password": "testpass123"})
            assert res.status_code == 403
        finally:
            u2 = db.query(User).filter(User.username == "_inactive_login_test").first()
            if u2:
                db.delete(u2)
                db.commit()
            db.close()

    def test_login_is_case_insensitive():
        from auth import hash_password
        from database import SessionLocal, init_db
        from models import AccountLevel, User
        init_db()
        db = SessionLocal()
        try:
            db.add(User(
                username="_Case_Login_Test", email="_case_login@test.internal",
                full_name="Case", password_hash=hash_password("testpass123"),
                account_level=AccountLevel.trial,
            ))
            db.commit()
            # Stored mixed-case, logging in all-lowercase must still authenticate.
            res = client.post("/auth/login", json={"username": "_case_login_test", "password": "testpass123"})
            assert res.status_code == 200, res.status_code
        finally:
            u = db.query(User).filter(User.username == "_Case_Login_Test").first()
            if u:
                db.delete(u)
                db.commit()
            db.close()

    def test_register_duplicate_username_case_insensitive():
        from auth import hash_password
        from database import SessionLocal, init_db
        from models import AccountLevel, User
        init_db()
        db = SessionLocal()
        try:
            db.add(User(
                username="_case_dup_test", email="_case_dup_existing@test.internal",
                full_name="Dup", password_hash=hash_password("testpass123"),
                account_level=AccountLevel.trial,
            ))
            db.commit()
            # A case variant of an existing username must be rejected as taken.
            res = client.post("/auth/register", json={
                "full_name": "Dup Two", "username": "_CASE_DUP_TEST",
                "email": "_case_dup_new@test.internal", "password": "testpass123",
            })
            assert res.status_code == 400, res.status_code
        finally:
            for filt in (User.username == "_case_dup_test", User.email == "_case_dup_new@test.internal"):
                x = db.query(User).filter(filt).first()
                if x:
                    db.delete(x)
                    db.commit()
            db.close()

    def _seed_login_user(db, username, email):
        from auth import hash_password
        from models import AccountLevel, User
        db.add(User(
            username=username, email=email, full_name="Ident",
            password_hash=hash_password("testpass123"), account_level=AccountLevel.trial,
        ))
        db.commit()

    def _login(identifier):
        """POSTs /auth/login, first clearing the limiter keys this call would trip. The per-IP
        counters accumulate across every test in the suite, so back-to-back logins in one test
        would otherwise 429 regardless of credentials."""
        import asyncio
        import server

        async def _clear():
            r = server.app.state.redis
            for key in (identifier.strip().lower(), "testclient"):
                for endpoint in ("login_user", "login_ip"):
                    await r.delete(f"rl:{key}:{endpoint}:last", f"rl:{key}:{endpoint}:count")
        asyncio.run(_clear())
        return client.post("/auth/login", json={"username": identifier, "password": "testpass123"})

    def test_login_accepts_email_identifier():
        from database import SessionLocal, init_db
        from models import User
        init_db()
        db = SessionLocal()
        try:
            _seed_login_user(db, "_ident_email_test", "_ident_email@test.internal")
            # The identifier field takes an email as readily as a username — the path that
            # matters for OAuth accounts, whose username was generated and never shown.
            assert _login("_ident_email@test.internal").status_code == 200
            # ...and case-insensitively, since what's typed isn't necessarily lowercased.
            assert _login("_IDENT_EMAIL@Test.Internal").status_code == 200
            # The username still works, unchanged.
            assert _login("_ident_email_test").status_code == 200
        finally:
            u = db.query(User).filter(User.username == "_ident_email_test").first()
            if u:
                db.delete(u)
                db.commit()
            db.close()

    def test_login_email_shaped_username_cannot_shadow_email():
        """An identifier containing '@' is matched against email and *only* email. Without that
        split, registering the username "<victim's email>" would shadow them at the prompt."""
        from database import SessionLocal, init_db
        from models import User
        init_db()
        db = SessionLocal()
        try:
            # Seeded directly (register would now reject the '@'), simulating a legacy row.
            _seed_login_user(db, "_squat@test.internal", "_squatter@test.internal")
            assert _login("_squat@test.internal").status_code == 401
            # The same account still signs in by its real email.
            assert _login("_squatter@test.internal").status_code == 200
        finally:
            u = db.query(User).filter(User.username == "_squat@test.internal").first()
            if u:
                db.delete(u)
                db.commit()
            db.close()

    def test_username_rules():
        """Unit-level check of the shared validator (avoids the register rate-limit cooldown,
        which would otherwise fire on back-to-back /auth/register calls)."""
        from auth import validate_username
        assert validate_username("_reg@name") is not None    # '@' — unreachable at login
        assert validate_username("_reg name") is not None    # whitespace
        assert validate_username("_reg+name") is not None    # outside the charset
        assert validate_username("ab") is not None           # under USERNAME_MIN_LENGTH
        assert validate_username("a" * 33) is not None       # over USERNAME_MAX_LENGTH
        assert validate_username("JohnS") is None
        assert validate_username("_ok.a-b_1") is None        # every allowed separator

    def test_register_rejects_invalid_username():
        """The validator above, wired into /auth/register."""
        import secrets as _sec
        tag = _sec.token_hex(4)
        res = client.post("/auth/register", json={
            "full_name": "Bad", "username": f"_reg@{tag}",
            "email": f"_reg_bad_{tag}@test.internal", "password": "testpass123",
        })
        assert res.status_code == 400, res.status_code

    test("Password hashing and verification",         test_password_hashing)
    test("JWT token creation and decode",             test_token_roundtrip)
    test("decode_user_id: garbage token -> None",     test_decode_user_id_garbage_returns_none)
    test("decode_user_id: expired token -> None",     test_decode_user_id_expired_returns_none)
    test("Login rejects inactive user (403)",         test_login_rejects_inactive_user)
    test("Login is case-insensitive on username",     test_login_is_case_insensitive)
    test("Register rejects case-variant duplicate",   test_register_duplicate_username_case_insensitive)
    test("Login accepts an email as the identifier",  test_login_accepts_email_identifier)
    test("Email-shaped username can't shadow email",  test_login_email_shaped_username_cannot_shadow_email)
    test("Username charset/length rules",             test_username_rules)
    test("Register rejects an invalid username",      test_register_rejects_invalid_username)
    test("Duplicate username rejected",               test_duplicate_username_rejected)
    test("Referral code generation — 10 unique",     test_referral_code_generation)
    test("Referral code is URL-safe",                 test_referral_code_is_url_safe)
    test("Forgot password — unknown email returns 200",   test_forgot_password_unknown_email)
    test("Forgot password — known email sets token",      test_forgot_password_sets_token)
    test("Reset password — valid token works",            test_reset_password_valid_token)
    test("Reset password — expired token rejected",       test_reset_password_expired_token)
    test("Reset password — invalid token rejected",       test_reset_password_invalid_token)
    test("Reset password — too-short password rejected",  test_reset_password_too_short)
    test("Reset password — token is single-use",          test_reset_token_single_use)
