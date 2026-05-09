import secrets as _sec

from auth import create_token, generate_unique_referral_code, hash_password
from database import SessionLocal
from models import AccountLevel, InterviewSession, Referral, User


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
        db.query(Referral).filter(
            (Referral.referrer_id == u.id) | (Referral.referee_id == u.id)
        ).delete()
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
