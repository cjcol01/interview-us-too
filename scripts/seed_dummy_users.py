"""Seeds dummy users covering a spread of real account states, for manual testing
against templates/admin pages without needing to work through real Stripe/signup flows.

Backs up users.db first (via sqlite3's backup API, so it's a consistent snapshot
even in WAL mode) to users.db.bak-<timestamp> next to it. Safe to re-run — skips
any dummy_* username that already exists.

Usage: python scripts/seed_dummy_users.py
"""
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DB_DATA_DIR, PARTNER_TIER2_BPS
from database import SessionLocal, init_db
from auth import generate_unique_referral_code, hash_password
from models import AccountLevel, CommissionStatus, InterviewSession, PartnerCommission, Referral, ReferralStatus, User

DUMMY_PASSWORD = "DummyPass123!"


def backup_db():
    data_dir = os.path.expanduser(DB_DATA_DIR)
    db_path = os.path.join(data_dir, "users.db")
    if not os.path.exists(db_path):
        print(f"No existing DB at {db_path} — nothing to back up.")
        return
    backup_path = f"{db_path}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(backup_path)
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    print(f"Backed up {db_path} -> {backup_path}")


def make_user(db, *, username, email, full_name, account_level, created_days_ago,
              last_login_days_ago=None, setup_complete=True, api_token=True, **kwargs):
    user = User(
        username=username,
        email=email,
        full_name=full_name,
        password_hash=hash_password(DUMMY_PASSWORD),
        account_level=account_level,
        email_verified=True,
        setup_complete=setup_complete,
        created_at=datetime.utcnow() - timedelta(days=created_days_ago),
        last_login=(datetime.utcnow() - timedelta(days=last_login_days_ago)) if last_login_days_ago is not None else None,
        api_token=secrets.token_urlsafe(32) if api_token else None,
        **kwargs,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user.referral_code = generate_unique_referral_code(db)
    db.commit()
    return user


def main():
    backup_db()
    init_db()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == "dummy_free1").first():
            print("Dummy users already seeded — skipping (delete them manually first to reseed).")
            return

        now = datetime.utcnow()

        # --- Partners (created first — referred users below point at them) ---
        partner1 = make_user(
            db, username="dummy_partner1", email="dummy.partner1@example.test",
            full_name="Dana Partner", account_level=AccountLevel.unlimited,
            created_days_ago=150, last_login_days_ago=1,
            stripe_customer_id="cus_dummy_partner1", stripe_sub_id="sub_dummy_partner1",
            sub_invoice_paid=True, partner_status="active", partner_tier=1,
        )
        partner2 = make_user(
            db, username="dummy_partner2", email="dummy.partner2@example.test",
            full_name="Priya Partner", account_level=AccountLevel.unlimited,
            created_days_ago=200, last_login_days_ago=0,
            stripe_customer_id="cus_dummy_partner2", stripe_sub_id="sub_dummy_partner2",
            sub_invoice_paid=True, partner_status="active", partner_tier=2,
        )
        make_user(
            db, username="dummy_partner_credit", email="dummy.partnercredit@example.test",
            full_name="Wesley Tier1", account_level=AccountLevel.unlimited,
            created_days_ago=20, last_login_days_ago=2,
            stripe_customer_id="cus_dummy_partnercredit", stripe_sub_id="sub_dummy_partnercredit",
            sub_invoice_paid=True, referral_credit_pence=500,
        )

        # --- Free ---
        make_user(
            db, username="dummy_free1", email="dummy.free1@example.test",
            full_name="Frankie Free", account_level=AccountLevel.free,
            created_days_ago=60, last_login_days_ago=55,
        )
        make_user(
            db, username="dummy_free2", email="dummy.free2@example.test",
            full_name="Farah Freeman", account_level=AccountLevel.free,
            created_days_ago=120, last_login_days_ago=10,
            stripe_customer_id="cus_dummy_free2", stripe_sub_id="sub_dummy_free2_lapsed",
            sub_invoice_paid=True,  # churned subscriber — paid before, lapsed since
        )

        # --- Trial ---
        make_user(
            db, username="dummy_trial1", email="dummy.trial1@example.test",
            full_name="Toby Trialist", account_level=AccountLevel.trial,
            created_days_ago=0, setup_complete=False, api_token=False,
        )
        trial2 = make_user(
            db, username="dummy_trial2", email="dummy.trial2@example.test",
            full_name="Tara Trialgoer", account_level=AccountLevel.trial,
            created_days_ago=2, last_login_days_ago=0,
            referred_by_id=partner1.id,
        )

        # --- Session packs (AccountLevel.paid) ---
        session1 = make_user(
            db, username="dummy_session1", email="dummy.session1@example.test",
            full_name="Sam Sessions", account_level=AccountLevel.paid,
            created_days_ago=30, last_login_days_ago=5,
            stripe_customer_id="cus_dummy_session1", sessions_remaining=2, intro_redeemed=True,
        )
        db.add(InterviewSession(
            user_id=session1.id,
            started_at=now - timedelta(days=5),
            expires_at=now - timedelta(days=5) + timedelta(hours=2, minutes=30),
            ended_at=now - timedelta(days=5) + timedelta(hours=2, minutes=30),
        ))

        session2 = make_user(
            db, username="dummy_session2", email="dummy.session2@example.test",
            full_name="Sasha Sessionless", account_level=AccountLevel.paid,
            created_days_ago=45, last_login_days_ago=3,
            stripe_customer_id="cus_dummy_session2", sessions_remaining=0, intro_redeemed=True,
            referred_by_id=partner2.id,
        )
        for days_ago in (40, 20):
            db.add(InterviewSession(
                user_id=session2.id,
                started_at=now - timedelta(days=days_ago),
                expires_at=now - timedelta(days=days_ago) + timedelta(hours=2, minutes=30),
                ended_at=now - timedelta(days=days_ago) + timedelta(hours=2, minutes=30),
            ))
        db.commit()

        # --- Unlimited (subscription) ---
        make_user(
            db, username="dummy_unlimited1", email="dummy.unlimited1@example.test",
            full_name="Uma Unlimited", account_level=AccountLevel.unlimited,
            created_days_ago=90, last_login_days_ago=0,
            stripe_customer_id="cus_dummy_unlimited1", stripe_sub_id="sub_dummy_unlimited1",
            sub_invoice_paid=True,
        )
        make_user(
            db, username="dummy_unlimited2", email="dummy.unlimited2@example.test",
            full_name="Ulric Unsubbing", account_level=AccountLevel.unlimited,
            created_days_ago=60, last_login_days_ago=1,
            stripe_customer_id="cus_dummy_unlimited2", stripe_sub_id="sub_dummy_unlimited2",
            sub_invoice_paid=True, sub_cancel_at=now + timedelta(days=18),
        )

        # --- Referrals tying the above together ---
        db.add(Referral(
            referrer_id=partner1.id, referee_id=trial2.id,
            status=ReferralStatus.signed_up,
            created_at=trial2.created_at,
        ))
        db.add(Referral(
            referrer_id=partner2.id, referee_id=session2.id,
            status=ReferralStatus.subscribed, intro_credited=True, sub_credited=True,
            created_at=session2.created_at,
            intro_at=session2.created_at,
            sub_at=session2.created_at + timedelta(days=15),
        ))
        db.commit()

        # --- Partner commissions for partner2, earned off session2's two purchases ---
        # First purchase: still within the hold window (pending). Second: matured (available).
        source_pence = 1500
        rate_bps = PARTNER_TIER2_BPS
        db.add(PartnerCommission(
            partner_id=partner2.id, referee_id=session2.id,
            source_amount_pence=source_pence, rate_bps=rate_bps,
            amount_pence=source_pence * rate_bps // 10000,
            kind="intro", status=CommissionStatus.pending,
            created_at=now - timedelta(days=5),
            mature_at=now + timedelta(days=25),
        ))
        db.add(PartnerCommission(
            partner_id=partner2.id, referee_id=session2.id,
            source_amount_pence=source_pence, rate_bps=rate_bps,
            amount_pence=source_pence * rate_bps // 10000,
            kind="sessions_pack", status=CommissionStatus.available,
            created_at=now - timedelta(days=20),
            mature_at=now - timedelta(days=5),
        ))
        db.commit()

        print("Seeded 11 dummy users (password for all: {!r}):".format(DUMMY_PASSWORD))
        for u in db.query(User).filter(User.username.like("dummy_%")).order_by(User.id).all():
            print(f"  {u.username:<24} {u.account_level.value:<10} partner={u.partner_status:<7} "
                  f"referred={'yes' if u.referred_by_id else 'no':<3} email={u.email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
