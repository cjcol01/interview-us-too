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
    from models import IntroCardFingerprint, InterviewSession, User  # noqa: F401 — ensures tables are registered
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
        ]
        for col, definition in migrations:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {definition}"))
