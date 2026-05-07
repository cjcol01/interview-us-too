def register(test, skip, client=None):

    def test_db_init():
        from database import init_db
        init_db()

    def test_crud():
        from auth import hash_password
        from database import SessionLocal, init_db
        from models import AccountLevel, User
        init_db()
        db = SessionLocal()
        try:
            u = User(
                username="_smoke_test_user", email="_smoke@test.internal",
                full_name="Smoke", password_hash=hash_password("test123"),
                account_level=AccountLevel.trial,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
            assert u.id is not None
            found = db.query(User).filter(User.username == "_smoke_test_user").first()
            assert found is not None and found.full_name == "Smoke"
            db.delete(found)
            db.commit()
            assert db.query(User).filter(User.username == "_smoke_test_user").first() is None
        finally:
            db.close()

    def test_referral_table_exists():
        from database import SessionLocal, init_db
        from models import Referral
        init_db()
        db = SessionLocal()
        try:
            db.query(Referral).count()
        finally:
            db.close()

    def test_user_has_referral_columns():
        from database import SessionLocal, init_db
        from models import User
        init_db()
        db = SessionLocal()
        try:
            u = db.query(User).first()
            if u:
                assert hasattr(u, "referral_code")
                assert hasattr(u, "referred_by_id")
        finally:
            db.close()

    test("Database initialises",                        test_db_init)
    test("Create / read / delete user",                 test_crud)
    test("Referral table exists",                       test_referral_table_exists)
    test("User model has referral columns",             test_user_has_referral_columns)
