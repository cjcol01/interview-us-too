import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text

from database import Base


class AccountLevel(str, enum.Enum):
    free      = "free"
    trial     = "trial"
    paid      = "paid"
    unlimited = "unlimited"


class User(Base):
    __tablename__ = "users"

    id           = Column(Integer, primary_key=True, index=True)
    username     = Column(String, unique=True, index=True, nullable=False)
    email        = Column(String, unique=True, index=True, nullable=False)
    full_name    = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    account_level = Column(Enum(AccountLevel), default=AccountLevel.trial, nullable=False)
    is_active          = Column(Boolean, default=True, nullable=False)
    created_at         = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login         = Column(DateTime, nullable=True)
    stripe_customer_id = Column(String, nullable=True, unique=True)
    stripe_sub_id      = Column(String, nullable=True, unique=True)
    api_token          = Column(String, nullable=True, unique=True)
    email_verified     = Column(Boolean, default=False, nullable=False)
    verify_token       = Column(String, nullable=True)
    setup_complete     = Column(Boolean, default=False, nullable=False)
    sessions_remaining = Column(Integer, default=0, nullable=False, server_default="0")
    intro_redeemed     = Column(Boolean, default=False, nullable=False, server_default="0")
    intro_declined     = Column(Boolean, default=False, nullable=False, server_default="0")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    ended_at   = Column(DateTime, nullable=True)


class IntroCardFingerprint(Base):
    __tablename__ = "intro_card_fingerprints"

    id          = Column(Integer, primary_key=True, index=True)
    fingerprint = Column(String, unique=True, nullable=False, index=True)
    used_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
