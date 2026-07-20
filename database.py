import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DB_DATA_DIR

# See DB_DATA_DIR in config.py for why this is configurable and what it defaults to.
# WAL mode below needs a real shared-memory-capable filesystem for its -wal/-shm sidecar
# files — don't point DB_DATA_DIR at a 9p/network mount.
DATA_DIR = os.path.expanduser(DB_DATA_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

_DB_FILENAME = "test_users.db" if os.getenv("TESTING") == "1" else "users.db"
DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, _DB_FILENAME)}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=20,
    max_overflow=20,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _):
    # WAL lets readers and writers proceed without blocking each other (SQLite is still
    # single-writer, but readers no longer stall behind a write holding the file lock).
    # busy_timeout makes a connection retry for 30s instead of raising "database is locked"
    # immediately when it does need to wait on the one writer.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import IntroCardFingerprint, InterviewContext, InterviewSession, PartnerCommission, Referral, UsageDaily, User  # noqa: F401 — ensures tables are registered
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
            ("partner_status",         "VARCHAR DEFAULT 'none'"),
            ("partner_tier",           "INTEGER DEFAULT 0"),
            ("reset_token",            "VARCHAR"),
            ("reset_token_expiry",     "DATETIME"),
            ("active_context_slot",    "INTEGER"),
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
    # one-off: migrate the old single custom_context text column (pre-multi-context) into
    # the new interview_contexts table, as slot 1, marked active for that user.
    if "custom_context" in existing:
        db = SessionLocal()
        try:
            rows = db.execute(text(
                "SELECT id, custom_context FROM users WHERE custom_context IS NOT NULL AND custom_context != ''"
            )).fetchall()
            for user_id, ctx_text in rows:
                if db.query(InterviewContext).filter(InterviewContext.user_id == user_id).first():
                    continue
                db.add(InterviewContext(user_id=user_id, slot=1, name="Imported context", text=ctx_text))
                db.query(User).filter(User.id == user_id).update({"active_context_slot": 1})
            db.commit()
        finally:
            db.close()
