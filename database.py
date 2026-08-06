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


def _add_missing_columns(conn, inspector, table, migrations):
    """Applies an idempotent list of (col, sql_type) ALTER TABLEs to `table` for any column
    not already present, so create_all()'s "new table" path and this "existing table" path
    both stay in sync without dropping data. Returns the pre-migration column set (some
    callers need to know whether a given column was newly added, e.g. for a backfill)."""
    from sqlalchemy import text
    existing = {c["name"] for c in inspector.get_columns(table)}
    for col, definition in migrations:
        if col not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))  # no-op if column exists
    return existing


def init_db():
    from models import Announcement, AnnouncementDismissal, IntroCardFingerprint, InterviewContext, InterviewSession, Lead, PartnerCommission, Referral, SessionFeedback, UsageDaily, User, Withdrawal  # noqa: F401 — ensures tables are registered
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
            ("typing_preview",      "BOOLEAN DEFAULT 1"),
            ("replay_enabled",         "BOOLEAN DEFAULT 1"),
            ("replay_seconds",         "INTEGER DEFAULT 15"),
            ("referral_credit_pence",  "INTEGER DEFAULT 0"),
            ("sub_trial_used",         "BOOLEAN DEFAULT 0"),
            ("sub_invoice_paid",       "BOOLEAN DEFAULT 0"),
            ("retention_offer_claimed","BOOLEAN DEFAULT 0"),
            ("partner_status",         "VARCHAR DEFAULT 'none'"),
            ("partner_tier",           "INTEGER DEFAULT 0"),
            ("partner_tier_manual",    "BOOLEAN DEFAULT 0"),
            ("reset_token",            "VARCHAR"),
            ("reset_token_expiry",     "DATETIME"),
            ("active_context_slot",    "INTEGER"),
            ("cv_context",             "TEXT"),
            ("behavioural_context",    "TEXT"),
            ("account_flag",           "VARCHAR"),
            ("account_flag_seen",      "BOOLEAN DEFAULT 1"),
            ("google_id",              "VARCHAR"),
            ("github_id",              "VARCHAR"),
            ("welcome_seen",            "BOOLEAN DEFAULT 0"),
            ("tutorial_seen",           "BOOLEAN DEFAULT 0"),
            ("interview_date",          "DATE"),
            ("interview_reminder_sent", "BOOLEAN DEFAULT 0"),
            ("password_set",            "BOOLEAN DEFAULT 1"),
        ]
        welcome_seen_is_new = "welcome_seen" not in existing
        tutorial_seen_is_new = "tutorial_seen" not in existing
        _add_missing_columns(conn, inspector, "users", migrations)
        # leads has no columns yet needing an ALTER — create_all() covers a brand-new table
        # in full. Kept here (empty) so the next column added to `leads` doesn't silently
        # do nothing on an existing DB, which create_all() alone would do.
        lead_migrations = []
        _add_missing_columns(conn, inspector, "leads", lead_migrations)
        # session_feedback is brand-new — create_all() covers it in full. Kept here (empty)
        # for the same reason as lead_migrations above: so the next column added to it
        # doesn't silently no-op on an existing DB.
        session_feedback_migrations = [
            ("session_type", "VARCHAR"),
        ]
        _add_missing_columns(conn, inspector, "session_feedback", session_feedback_migrations)
        if welcome_seen_is_new:
            # anyone who'd already finished onboarding before this column existed has
            # necessarily already seen the welcome demo — don't replay it for them
            conn.execute(text("UPDATE users SET welcome_seen = 1 WHERE setup_complete = 1"))
        if tutorial_seen_is_new:
            # Same reasoning one step further along: this flag used to live in per-device
            # localStorage, which we can't read from here. welcome_seen is the closest
            # server-side proxy — anyone past the welcome step has been shown the demo (or
            # explicitly skipped it), so don't spring it on them again on their next visit.
            conn.execute(text("UPDATE users SET tutorial_seen = 1 WHERE welcome_seen = 1"))
        # index=True on a model only applies via create_all() for brand-new tables — add it
        # explicitly here so existing (pre-change) databases pick it up too.
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_interview_sessions_user_id ON interview_sessions(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_verify_token ON users(verify_token)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_users_reset_token ON users(reset_token)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users(google_id)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_github_id ON users(github_id)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_leads_email ON leads(email)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_leads_token_hash ON leads(token_hash)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_created_at ON leads(created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_user_id ON leads(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_claimed_at ON leads(claimed_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_session_feedback_user_id ON session_feedback(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_session_feedback_created_at ON session_feedback(created_at)"))
    # backfill referral codes for any existing users that don't have one
    db = SessionLocal()
    try:
        from auth import generate_unique_referral_code
        for u in db.query(User).filter(User.referral_code == None).all():  # noqa: E711
            u.referral_code = generate_unique_referral_code(db)
        db.commit()
    finally:
        db.close()
    # normalize any pre-existing mixed-case emails now that every signup path (register,
    # Google/GitHub OAuth, /claim) consistently lowercases going forward — without this,
    # an old mixed-case row would be invisible to those paths' now-lowercased lookups.
    # Skips (rather than crashes on a UNIQUE violation) if lowercasing a row would collide
    # with another account — that would mean two accounts already differing only by case,
    # which needs a human to resolve, not a silent merge.
    db = SessionLocal()
    try:
        from analytics import logger
        for u in db.query(User).all():
            lowered = u.email.lower()
            if lowered == u.email:
                continue
            if db.query(User).filter(User.email == lowered, User.id != u.id).first():
                logger.warning("[init_db] skipping email lowercase for user %s — %s already taken", u.id, lowered)
                continue
            u.email = lowered
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
