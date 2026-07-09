import enum
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text

from database import Base


class AccountLevel(str, enum.Enum):
    free      = "free"
    trial     = "trial"
    paid      = "paid"
    unlimited = "unlimited"


class ResponseStyle(str, enum.Enum):
    conversational = "conversational"
    bullets        = "bullets"
    summary        = "summary"
    one_liner      = "one_liner"


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
    reset_token        = Column(String, nullable=True)
    reset_token_expiry = Column(DateTime, nullable=True)
    setup_complete     = Column(Boolean, default=False, nullable=False)
    sessions_remaining = Column(Integer, default=0, nullable=False, server_default="0")
    intro_redeemed     = Column(Boolean, default=False, nullable=False, server_default="0")
    intro_declined     = Column(Boolean, default=False, nullable=False, server_default="0")
    sub_cancel_at      = Column(DateTime, nullable=True)
    referral_code      = Column(String, nullable=True, unique=True, index=True)
    referred_by_id     = Column(Integer, ForeignKey("users.id"), nullable=True)
    hotkey_capture     = Column(String, nullable=True)
    hotkey_audio       = Column(String, nullable=True)
    hotkey_toggle      = Column(String, nullable=True)
    hotkey_replay      = Column(String, nullable=True)
    hotkey_typing      = Column(String, nullable=True)
    typing_passthrough = Column(Boolean, default=True, nullable=False, server_default="1")
    response_style     = Column(Enum(ResponseStyle), nullable=True)
    replay_enabled     = Column(Boolean, default=False, nullable=False, server_default="0")
    replay_seconds     = Column(Integer, default=10,    nullable=False, server_default="10")
    referral_credit_pence = Column(Integer, default=0, nullable=False, server_default="0")
    sub_trial_used     = Column(Boolean, default=False, nullable=False, server_default="0")
    sub_invoice_paid   = Column(Boolean, default=False, nullable=False, server_default="0")
    retention_offer_claimed = Column(Boolean, default=False, nullable=False, server_default="0")
    partner_waitlist        = Column(Boolean, default=False, nullable=False, server_default="0")
    custom_context     = Column(Text, nullable=True)


class ReferralStatus(str, enum.Enum):
    signed_up  = "signed_up"
    intro      = "intro"
    subscribed = "subscribed"


class Referral(Base):
    __tablename__ = "referrals"

    id             = Column(Integer, primary_key=True, index=True)
    referrer_id    = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    referee_id     = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    status         = Column(Enum(ReferralStatus), default=ReferralStatus.signed_up, nullable=False)
    intro_credited = Column(Boolean, default=False, nullable=False)
    sub_credited   = Column(Boolean, default=False, nullable=False)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    intro_at       = Column(DateTime, nullable=True)
    sub_at         = Column(DateTime, nullable=True)


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
