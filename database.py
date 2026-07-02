from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./users.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import IntroCardFingerprint, InterviewSession, Referral, User  # noqa: F401 — ensures tables are registered
    from sqlalchemy import inspect, text
    Base.metadata.create_all(bind=engine)
    # add new columns to existing DBs without dropping data
    inspector = inspect(engine)
    existing = {c["name"] for c in inspector.get_columns("users")}
    with engine.begin() as conn:
        migrations = [
            ("stripe_customer_id", "VARCHAR"),
            ("stripe_sub_id",      "VARCHAR"),
            ("api_token",          "VARCHAR"),
            ("verify_token",       "VARCHAR"),
            ("email_verified",      "BOOLEAN DEFAULT 0"),
            ("setup_complete",      "BOOLEAN DEFAULT 0"),
            ("sessions_remaining",  "INTEGER DEFAULT 0"),
            ("intro_redeemed",      "BOOLEAN DEFAULT 0"),
            ("intro_declined",      "BOOLEAN DEFAULT 0"),
            ("sub_cancel_at",       "DATETIME"),
            ("referral_code",       "VARCHAR"),
            ("referred_by_id",      "INTEGER"),
            ("hotkey_capture",      "VARCHAR"),
            ("hotkey_audio",        "VARCHAR"),
            ("hotkey_toggle",       "VARCHAR"),
            ("hotkey_replay",       "VARCHAR"),
            ("hotkey_typing",       "VARCHAR"),
            ("typing_passthrough",  "BOOLEAN DEFAULT 1"),
            ("replay_enabled",         "BOOLEAN DEFAULT 0"),
            ("replay_seconds",         "INTEGER DEFAULT 10"),
            ("referral_credit_pence",  "INTEGER DEFAULT 0"),
            ("sub_trial_used",         "BOOLEAN DEFAULT 0"),
            ("sub_invoice_paid",       "BOOLEAN DEFAULT 0"),
            ("retention_offer_claimed","BOOLEAN DEFAULT 0"),
            ("partner_waitlist",       "BOOLEAN DEFAULT 0"),
            ("reset_token",            "VARCHAR"),
            ("reset_token_expiry",     "DATETIME"),
        ]
        for col, definition in migrations:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {definition}"))  # no-op if column exists
    # backfill referral codes for any existing users that don't have one
    db = SessionLocal()
    try:
        from auth import generate_unique_referral_code
        for u in db.query(User).filter(User.referral_code == None).all():  # noqa: E711
            u.referral_code = generate_unique_referral_code(db)
        db.commit()
    finally:
        db.close()
