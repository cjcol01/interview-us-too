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
                "new_password": "newpass456",
            })
            assert res.status_code == 200, res.text

            db.expire(u)
            db.refresh(u)
            assert verify_password("newpass456", u.password_hash)
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

            res = client.post("/auth/reset-password", json={"token": token, "new_password": "newpass456"})
            assert res.status_code == 200

            # Second use with the same token should fail
            res2 = client.post("/auth/reset-password", json={"token": token, "new_password": "anotherpass789"})
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

    test("Password hashing and verification",         test_password_hashing)
    test("JWT token creation and decode",             test_token_roundtrip)
    test("decode_user_id: garbage token -> None",     test_decode_user_id_garbage_returns_none)
    test("decode_user_id: expired token -> None",     test_decode_user_id_expired_returns_none)
    test("Login rejects inactive user (403)",         test_login_rejects_inactive_user)
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
