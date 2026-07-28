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

    def test_lead_table_exists():
        from database import SessionLocal, init_db
        from models import Lead
        init_db()
        db = SessionLocal()
        try:
            db.query(Lead).count()
        finally:
            db.close()

    def test_init_db_lowercases_mixed_case_emails():
        """init_db()'s backfill normalizes any pre-existing mixed-case email now that every
        signup path writes lowercase going forward — otherwise an old row would be invisible
        to those paths' now-lowercased lookups."""
        from auth import hash_password
        from database import SessionLocal, init_db
        from models import AccountLevel, User
        db = SessionLocal()
        try:
            u = User(
                username="_case_backfill_user", email="MixedCase@Backfill.internal",
                full_name="Case Backfill", password_hash=hash_password("test123"),
                account_level=AccountLevel.trial,
            )
            db.add(u)
            db.commit()
            init_db()
            db.expire(u)
            db.refresh(u)
            assert u.email == "mixedcase@backfill.internal"
        finally:
            db.delete(u)
            db.commit()
            db.close()

    def test_init_db_skips_lowercasing_on_collision():
        """If lowercasing a row would collide with another account (two rows already
        differing only by case), the backfill must skip it rather than crash the whole
        boot on a UNIQUE constraint violation."""
        from auth import hash_password
        from database import SessionLocal, init_db
        from models import AccountLevel, User
        db = SessionLocal()
        u1 = u2 = None
        try:
            u1 = User(
                username="_case_collide_lower", email="collide@backfill.internal",
                full_name="Lower", password_hash=hash_password("test123"),
                account_level=AccountLevel.trial,
            )
            u2 = User(
                username="_case_collide_upper", email="Collide@Backfill.internal",
                full_name="Upper", password_hash=hash_password("test123"),
                account_level=AccountLevel.trial,
            )
            db.add(u1)
            db.add(u2)
            db.commit()
            init_db()  # must not raise
            db.expire(u1)
            db.expire(u2)
            db.refresh(u1)
            db.refresh(u2)
            assert u1.email == "collide@backfill.internal"
            assert u2.email == "Collide@Backfill.internal"  # left untouched, not silently merged
        finally:
            if u1:
                db.delete(u1)
            if u2:
                db.delete(u2)
            db.commit()
            db.close()

    test("Database initialises",                        test_db_init)
    test("Create / read / delete user",                 test_crud)
    test("Referral table exists",                       test_referral_table_exists)
    test("User model has referral columns",             test_user_has_referral_columns)
    test("Lead table exists",                           test_lead_table_exists)
    test("init_db lowercases pre-existing mixed-case emails",  test_init_db_lowercases_mixed_case_emails)
    test("init_db skips lowercasing on collision",              test_init_db_skips_lowercasing_on_collision)
