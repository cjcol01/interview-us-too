import enum
from datetime import date as _date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint

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
    google_id          = Column(String, nullable=True, unique=True, index=True)
    github_id          = Column(String, nullable=True, unique=True, index=True)
    email_verified     = Column(Boolean, default=False, nullable=False)
    # Whether this account has a password only the user knows. True for normal signups
    # (chosen at registration) and for Google/GitHub accounts (they always re-auth via that
    # provider, so a password is never needed). False only for accounts created via the
    # mobile device-handoff /claim flow, until they complete /finish-signup — that flow
    # proves email ownership but never collects a password, unlike every other signup path.
    password_set       = Column(Boolean, default=True, nullable=False, server_default="1")
    verify_token       = Column(String, nullable=True, index=True)
    reset_token        = Column(String, nullable=True, index=True)
    reset_token_expiry = Column(DateTime, nullable=True)
    setup_complete     = Column(Boolean, default=False, nullable=False)
    welcome_seen       = Column(Boolean, default=False, nullable=False)
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
    replay_enabled     = Column(Boolean, default=True, nullable=False, server_default="1")
    replay_seconds     = Column(Integer, default=10,    nullable=False, server_default="10")
    referral_credit_pence = Column(Integer, default=0, nullable=False, server_default="0")
    sub_trial_used     = Column(Boolean, default=False, nullable=False, server_default="0")
    sub_invoice_paid   = Column(Boolean, default=False, nullable=False, server_default="0")
    retention_offer_claimed = Column(Boolean, default=False, nullable=False, server_default="0")
    partner_status     = Column(String, default="none", nullable=False, server_default="none")  # none | active (active = upgraded to a %-commission tier)
    partner_tier       = Column(Integer, default=0, nullable=False, server_default="0")  # 0/1 = implicit flat Tier 1 | 2 = 15% | 3 = 25%
    partner_tier_manual = Column(Boolean, default=False, nullable=False, server_default="0")  # admin-granted tier — sticky, never auto-downgraded
    active_context_slot = Column(Integer, nullable=True)  # which InterviewContext.slot (company context) is sent to the AI
    cv_context          = Column(Text, nullable=True)  # single fixed personal context: the candidate's CV/background
    behavioural_context = Column(Text, nullable=True)  # single fixed personal context: STAR stories / behavioural prep
    account_flag        = Column(String, nullable=True)  # e.g. "paused" — set by admin actions, cleared once seen
    account_flag_seen   = Column(Boolean, default=True, nullable=False, server_default="1")
    interview_date         = Column(Date, nullable=True)  # user-supplied date of their real interview, for the day-before reminder email
    interview_reminder_sent = Column(Boolean, default=False, nullable=False, server_default="0")


class InterviewContext(Base):
    __tablename__ = "interview_contexts"
    __table_args__ = (UniqueConstraint("user_id", "slot", name="uq_interview_context_user_slot"),)

    id      = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    slot    = Column(Integer, nullable=False)  # 1..MAX_CONTEXTS_PER_USER (server.py)
    name    = Column(String, nullable=False, default="")
    text    = Column(Text, nullable=False, default="")


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


class CommissionStatus(str, enum.Enum):
    pending   = "pending"    # within the hold window
    available = "available"  # matured, withdrawable (future payout)
    paid      = "paid"       # cash paid out (future)
    reversed  = "reversed"   # refund/chargeback clawback (future)


class PartnerCommission(Base):
    __tablename__ = "partner_commissions"

    id                  = Column(Integer, primary_key=True, index=True)
    partner_id          = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    referee_id          = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source_amount_pence = Column(Integer, nullable=False)  # what we earned on this payment
    rate_bps            = Column(Integer, nullable=False)  # 1500 / 2500 at time of accrual
    amount_pence        = Column(Integer, nullable=False)  # the commission itself
    kind                = Column(String, nullable=False)   # subscription | sessions_pack | intro
    stripe_ref          = Column(String, nullable=True, unique=True, index=True)  # invoice/session id — idempotency
    status              = Column(Enum(CommissionStatus), default=CommissionStatus.pending, nullable=False)
    created_at          = Column(DateTime, default=datetime.utcnow, nullable=False)
    mature_at           = Column(DateTime, nullable=False)  # created_at, or +hold for first commission per referee


class WithdrawalStatus(str, enum.Enum):
    requested = "requested"  # partner asked to cash out — awaiting manual payout
    paid      = "paid"       # admin has sent the money
    rejected  = "rejected"   # declined (e.g. bad details) — releases the held balance


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id           = Column(Integer, primary_key=True, index=True)
    partner_id   = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount_pence = Column(Integer, nullable=False)
    method       = Column(String, nullable=False)   # bank | paypal
    destination  = Column(String, nullable=False)   # account details / PayPal email (free text)
    status       = Column(Enum(WithdrawalStatus), default=WithdrawalStatus.requested, nullable=False)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at      = Column(DateTime, nullable=True)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    ended_at   = Column(DateTime, nullable=True)


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_usage_daily_user_date"),)

    id            = Column(Integer, primary_key=True, index=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date          = Column(Date, nullable=False, default=_date.today, index=True)
    capture_count = Column(Integer, default=0, nullable=False)
    audio_count   = Column(Integer, default=0, nullable=False)


class IntroCardFingerprint(Base):
    __tablename__ = "intro_card_fingerprints"

    id          = Column(Integer, primary_key=True, index=True)
    fingerprint = Column(String, unique=True, nullable=False, index=True)
    used_at     = Column(DateTime, default=datetime.utcnow, nullable=False)


class Announcement(Base):
    __tablename__ = "announcements"

    id                     = Column(Integer, primary_key=True, index=True)
    created_at             = Column(DateTime, default=datetime.utcnow, nullable=False)
    subject                = Column(String, nullable=False)
    body                   = Column(Text, nullable=False)
    channel                = Column(String, nullable=False)   # email | in_app | both
    segment                = Column(String, nullable=False)   # see server.py _SEGMENTS
    target_email           = Column(String, nullable=True)    # only for segment == "individual"
    in_app_active          = Column(Boolean, default=False, nullable=False, server_default="0")
    email_recipient_count  = Column(Integer, nullable=True)   # set once the background send finishes


class AnnouncementDismissal(Base):
    __tablename__ = "announcement_dismissals"
    __table_args__ = (UniqueConstraint("announcement_id", "user_id", name="uq_dismissal_announcement_user"),)

    id              = Column(Integer, primary_key=True, index=True)
    announcement_id = Column(Integer, ForeignKey("announcements.id"), nullable=False, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)


class Lead(Base):
    """A captured email from the mobile landing-page CTA, before any account exists.

    Deliberately NOT a shell User row: a lead is inert — it doesn't block a later normal
    signup, doesn't need a synthesised username/full_name, and doesn't pollute user counts
    or get a referral code from init_db()'s backfill. The User row is created at CLAIM time
    (see /claim in server.py), which is the moment email ownership is actually proven.

    One row per email — re-requesting rotates token_hash and invalidates the previous link
    rather than accumulating rows, which matters most for kind == "existing" (a stale live
    login URL must not sit around in an inbox)."""
    __tablename__ = "leads"

    id             = Column(Integer, primary_key=True, index=True)
    email          = Column(String, unique=True, index=True, nullable=False)
    token_hash     = Column(String, unique=True, index=True, nullable=True)  # sha256 hex of the raw link token; nullable so the purge job can scrub it
    kind           = Column(String, nullable=False, server_default="new")    # new | existing
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    requested_at   = Column(DateTime, default=datetime.utcnow, nullable=False)  # last time a link was emailed
    request_count  = Column(Integer, default=0, nullable=False, server_default="0")
    expires_at     = Column(DateTime, nullable=False)
    claimed_at     = Column(DateTime, nullable=True, index=True)
    claim_count    = Column(Integer, default=0, nullable=False, server_default="0")
    user_id        = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    interview_date = Column(Date, nullable=True)   # transferred onto User at claim
    ref_code       = Column(String, nullable=True) # snapshot of the `ref` cookie at capture time — survives the device hop
    attribution    = Column(Text, nullable=True)   # JSON blob: utm_*, gclid, fbclid, referer, first-touch ts
    ip             = Column(String, nullable=True) # abuse triage only; scrubbed by the purge job


class SessionFeedback(Base):
    """One row per "how did your interview go?" submission, shown from a dashboard
    button the user clicks once they've done real interview work (see the client-side
    answer counter in templates/index.html). Deliberately NOT tied to InterviewSession —
    that model is a billing meter (paid-only, never created for unlimited accounts, never
    created by audio-only capture), not an interview. answer_count/duration_seconds are
    client-reported and informational only — never used for gating or billing."""
    __tablename__ = "session_feedback"

    id                  = Column(Integer, primary_key=True, index=True)
    user_id             = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    rating              = Column(Integer, nullable=False)  # 1..5
    comment             = Column(Text, nullable=True)
    next_interview_date = Column(Date, nullable=True)
    answer_count        = Column(Integer, nullable=True)
    duration_seconds    = Column(Integer, nullable=True)
    session_type        = Column(String, nullable=True)   # real | practice | testing | '' (not provided)
    created_at          = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
