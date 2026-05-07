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

    test("Password hashing and verification",         test_password_hashing)
    test("JWT token creation and decode",             test_token_roundtrip)
    test("Duplicate username rejected",               test_duplicate_username_rejected)
    test("Referral code generation — 10 unique",     test_referral_code_generation)
    test("Referral code is URL-safe",                 test_referral_code_is_url_safe)
