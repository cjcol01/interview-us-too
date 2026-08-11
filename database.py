import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from config import DATABASE_URL, DB_DATA_DIR, TEST_DATABASE_URL

# DB_DATA_DIR is used for non-DB persistent files: app.log (analytics.py) and disk health
# checks (server.py). Point it at a mounted volume on Railway so those files survive redeploys.
DATA_DIR = os.path.expanduser(DB_DATA_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

_url = TEST_DATABASE_URL if os.getenv("TESTING") == "1" else DATABASE_URL
if not _url:
    _which = "TEST_DATABASE_URL" if os.getenv("TESTING") == "1" else "DATABASE_URL"
    raise RuntimeError(
        f"{_which} env var is not set.\n"
        "Quick start (local dev):\n"
        "  docker run -d --name pg-iut -e POSTGRES_PASSWORD=dev -p 5432:5432 postgres:16\n"
        "  export DATABASE_URL=postgresql://postgres:dev@localhost:5432/iut\n"
        "  export TEST_DATABASE_URL=postgresql://postgres:dev@localhost:5432/iut_test"
    )

if os.getenv("TESTING") == "1":
    # NullPool: each session gets a fresh connection that is closed (not returned to a pool)
    # when the session closes. This means a leaked connection (e.g. from an exception inside
    # a finally block) just closes rather than starving the pool and failing all subsequent tests.
    engine = create_engine(_url, poolclass=NullPool)
else:
    engine = create_engine(
        _url,
        pool_size=5,
        max_overflow=10,
        # Re-validate connections on checkout — Railway drops idle connections after a quiet
        # period, and without this the first post-idle request fails with a stale-connection error.
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models import Announcement, AnnouncementDismissal, IntroCardFingerprint, InterviewContext, InterviewSession, Lead, PartnerCommission, Referral, SessionFeedback, UsageDaily, User, Withdrawal  # noqa: F401 — ensures tables are registered with Base.metadata before create_all

    # Always create any missing tables — safe no-op on existing tables.
    # On a fresh DB (Railway first deploy) this sets up the full schema from models.py,
    # so all FKs are created correctly; Alembic is then stamped at head rather than run.
    Base.metadata.create_all(bind=engine)

    if os.getenv("TESTING") != "1":
        # Apply any pending Alembic migrations (schema changes added after the baseline).
        # On a fresh DB that create_all() just set up, stamp at head instead — the schema
        # is already correct; the migrations only handle incremental diffs for existing DBs.
        from alembic.config import Config as _AlembicConfig
        from alembic import command as _alembic
        _alembic_cfg = _AlembicConfig(os.path.join(os.path.dirname(os.path.abspath(__file__)), "alembic.ini"))
        _db = SessionLocal()
        try:
            _tracked = _db.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'alembic_version')"
            )).scalar()
        finally:
            _db.close()
        if _tracked:
            _alembic.upgrade(_alembic_cfg, "head")
        else:
            # Fresh or pre-Alembic DB — stamp at head so future migrations apply from here.
            _alembic.stamp(_alembic_cfg, "head")

    # backfill referral codes for any existing users that don't have one
    db = SessionLocal()
    try:
        from auth import generate_unique_referral_code
        for u in db.query(User).filter(User.referral_code == None).all():  # noqa: E711
            u.referral_code = generate_unique_referral_code(db)
        db.commit()
    finally:
        db.close()
