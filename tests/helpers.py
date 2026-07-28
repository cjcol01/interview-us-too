import secrets as _sec
from datetime import datetime, timedelta
from pathlib import Path

from auth import create_token, generate_unique_referral_code, hash_password
from database import SessionLocal
from models import AccountLevel, InterviewContext, InterviewSession, Lead, PartnerCommission, Referral, UsageDaily, User, Withdrawal

_AUDIO_FIXTURE = Path(__file__).parent / "fixtures" / "test_audio.wav"


def fake_audio_bytes():
    """Real WAV bytes for tests that mock out transcription but still post to
    /api/audio-capture — server.py rejects anything under 2000 bytes as "no audio
    was captured" before it ever reaches the (mocked) transcription call."""
    return _AUDIO_FIXTURE.read_bytes()


def make_user(db, account_level=AccountLevel.trial, *, with_code=True, stripe_id=None):
    tag = _sec.token_hex(4)
    u = User(
        username=f"_test_{tag}",
        email=f"_test_{tag}@test.internal",
        full_name="Test User",
        password_hash=hash_password("testpass123"),
        account_level=account_level,
        api_token=_sec.token_urlsafe(32),
    )
    if stripe_id is not None:
        u.stripe_customer_id = stripe_id
    db.add(u)
    db.commit()
    db.refresh(u)
    if with_code:
        u.referral_code = generate_unique_referral_code(db)
        db.commit()
    return u


def make_cookie(account_level=AccountLevel.trial):
    db = SessionLocal()
    try:
        u = make_user(db, account_level)
        return create_token(u.id), u.username
    finally:
        db.close()


def cleanup(db, *users):
    import asyncio
    for u in users:
        if u is None:
            continue
        try:
            import server as _s
            asyncio.run(_s.app.state.redis.delete(
                f"rl:{u.id}:audio:last",   f"rl:{u.id}:audio:count",
                f"rl:{u.id}:capture:last", f"rl:{u.id}:capture:count",
            ))
        except Exception:
            pass
        db.query(InterviewSession).filter(InterviewSession.user_id == u.id).delete()
        db.query(InterviewContext).filter(InterviewContext.user_id == u.id).delete()
        db.query(UsageDaily).filter(UsageDaily.user_id == u.id).delete()
        db.query(Referral).filter(
            (Referral.referrer_id == u.id) | (Referral.referee_id == u.id)
        ).delete()
        db.query(PartnerCommission).filter(
            (PartnerCommission.partner_id == u.id) | (PartnerCommission.referee_id == u.id)
        ).delete()
        db.query(Withdrawal).filter(Withdrawal.partner_id == u.id).delete()
        db.query(Lead).filter(Lead.user_id == u.id).delete()
        db.delete(u)
    db.commit()


def delete_by_name(username):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == username).first()
        if u:
            cleanup(db, u)
    finally:
        db.close()


def delete_lead(email):
    """Cleanup for tests/test_install_link.py cases that create a Lead without ever
    creating a User (email unique constraint would otherwise cascade across runs)."""
    db = SessionLocal()
    try:
        db.query(Lead).filter(Lead.email == email).delete()
        db.commit()
    finally:
        db.close()


def delete_leads(db, *emails):
    """Session-taking twin of delete_lead — for tests that already hold a db session and
    want cleanup in the same transaction rather than opening a second one."""
    db.query(Lead).filter(Lead.email.in_([e for e in emails if e])).delete(synchronize_session=False)
    db.commit()


def make_lead(db, *, email=None, kind="new", claimed=False, user=None, attribution=None,
              created_at=None, interview_date=None):
    """Lead fixture for the admin leads/funnel/attribution tests. Mirrors what
    server._rotate_lead_token writes, without needing a live token or an email send."""
    now = created_at or datetime.utcnow()
    email = email or f"_lead_{_sec.token_hex(4)}@test.internal"
    lead = Lead(
        email=email,
        token_hash=_sec.token_hex(32),
        kind=kind,
        created_at=now,
        requested_at=now,
        expires_at=now + timedelta(days=14),
        interview_date=interview_date,
        attribution=attribution,
    )
    if claimed:
        lead.claimed_at = now
        lead.claim_count = 1
        if user is not None:
            lead.user_id = user.id
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead
