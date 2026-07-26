"""
Partner (affiliate) programme tests — the three-tier model: implicit Tier-1 flat cash on a
referee's first paid plan, recurring % for Tiers 2/3, auto-upgrade at 3 paid referrals, manual
tier grants, the first-payment hold, webhook idempotency, the dashboard, and cash withdrawals.
"""
import secrets as _sec
from datetime import datetime, timedelta
from unittest.mock import patch

from auth import create_token
from config import PARTNER_TIER1_FLAT_PENCE, PARTNER_WITHDRAWAL_THRESHOLD_PENCE
from database import SessionLocal, init_db
from models import AccountLevel, CommissionStatus, PartnerCommission, Referral, ReferralStatus, User, Withdrawal, WithdrawalStatus
from tests.helpers import cleanup, delete_by_name, make_cookie, make_user


class _FakeStripeObject(dict):
    def to_dict(self):
        return dict(self)


def _stripe_id():
    return f"cus_test_{_sec.token_hex(6)}"


def _sub_id():
    return f"sub_test_{_sec.token_hex(6)}"


def _checkout_data(customer_id, plan, amount_total=500, session_id=None):
    return _FakeStripeObject({
        "id": session_id or f"cs_test_{_sec.token_hex(6)}",
        "customer": customer_id,
        "mode": "payment",
        "payment_intent": "pi_test",
        "metadata": {"plan": plan},
        "amount_total": amount_total,
    })


def _invoice(customer_id, amount_paid=1000, invoice_id=None):
    return {
        "id": invoice_id or f"in_test_{_sec.token_hex(6)}",
        "customer": customer_id,
        "amount_paid": amount_paid,
        "starting_balance": 0,
        "ending_balance": 0,
    }


def _make_upgraded_partner(db, tier, cid=None, manual=False):
    p = make_user(db, AccountLevel.unlimited, stripe_id=cid or _stripe_id())
    p.partner_status = "active"
    p.partner_tier = tier
    p.partner_tier_manual = manual
    db.commit()
    return p


def register(test, skip, client):
    from billing import _handle_invoice_paid, _handle_sessions_purchase, _sync_subscription, _partner_rate_bps

    # -- Join is now a no-op (Tier 1 is automatic) ----------------------------

    def test_join_redirects_to_dashboard():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.post("/partner/join", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/partner/dashboard" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    def test_join_requires_auth():
        r = client.post("/partner/join", follow_redirects=False)
        assert r.status_code in (302, 303, 307, 401, 403)

    test("POST /partner/join redirects to dashboard (Tier 1 is automatic)", test_join_redirects_to_dashboard)
    test("POST /partner/join requires auth",                                test_join_requires_auth)

    # -- Tier 1 flat reward ---------------------------------------------------

    def test_no_reward_on_intro():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=_stripe_id())
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            with patch("billing.stripe.Customer.create_balance_transaction"):
                _handle_sessions_purchase(_checkout_data(referee_cid, "sessions", amount_total=200), db)

            assert db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first() is None
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_tier1_flat_reward_on_pack():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=_stripe_id())  # default = Tier 1
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            with patch("billing.stripe.Customer.create_balance_transaction"):
                _handle_sessions_purchase(_checkout_data(referee_cid, "sessions_pack", amount_total=1000), db)

            c = db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first()
            assert c is not None
            assert c.kind == "referral_flat"
            assert c.amount_pence == PARTNER_TIER1_FLAT_PENCE == 500
            assert c.status == CommissionStatus.pending
            assert c.mature_at > datetime.utcnow() + timedelta(days=1)
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_tier1_no_recurring_on_invoice():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=_stripe_id())  # Tier 1
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            _handle_invoice_paid(_invoice(referee_cid, amount_paid=1500), db)
            # Tier 1 earns nothing on a recurring invoice — the flat reward comes at conversion only.
            assert db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first() is None
        finally:
            cleanup(db, referrer, referee); db.close()

    test("No referrer reward on referee intro",                  test_no_reward_on_intro)
    test("Tier 1 earns flat £5 on referee sessions pack",        test_tier1_flat_reward_on_pack)
    test("Tier 1 earns nothing on recurring invoices",           test_tier1_no_recurring_on_invoice)

    # -- Recurring commission (Tiers 2/3) -------------------------------------

    def test_tier2_earns_15pct_on_invoice():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer = _make_upgraded_partner(db, 2)
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            _handle_invoice_paid(_invoice(referee_cid, amount_paid=1000), db)
            c = db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first()
            assert c.amount_pence == 150  # 15% of 1000p
            assert c.rate_bps == 1500
            assert c.kind == "subscription"
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_tier3_earns_25pct_on_invoice():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer = _make_upgraded_partner(db, 3, manual=True)
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            _handle_invoice_paid(_invoice(referee_cid, amount_paid=1000), db)
            c = db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first()
            assert c.amount_pence == 250  # 25% of 1000p
            assert c.rate_bps == 2500
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_rate_bps_by_tier():
        init_db()
        db = SessionLocal()
        t1 = t2 = t3 = None
        try:
            t1 = make_user(db, AccountLevel.unlimited, stripe_id=_stripe_id())
            t2 = _make_upgraded_partner(db, 2)
            t3 = _make_upgraded_partner(db, 3, manual=True)
            assert _partner_rate_bps(t1) == 0
            assert _partner_rate_bps(t2) == 1500
            assert _partner_rate_bps(t3) == 2500
        finally:
            cleanup(db, t1, t2, t3); db.close()

    test("Tier 2 earns 15% on subscription invoice", test_tier2_earns_15pct_on_invoice)
    test("Tier 3 earns 25% on subscription invoice", test_tier3_earns_25pct_on_invoice)
    test("_partner_rate_bps: 0 / 1500 / 2500 by tier", test_rate_bps_by_tier)

    # -- Hold rule & idempotency (Tier 2) -------------------------------------

    def test_first_commission_held_second_matures_immediately():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer = _make_upgraded_partner(db, 2)
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            _handle_invoice_paid(_invoice(referee_cid, amount_paid=1000), db)
            _handle_invoice_paid(_invoice(referee_cid, amount_paid=1000), db)  # renewal, different id

            commissions = (
                db.query(PartnerCommission)
                .filter(PartnerCommission.partner_id == referrer.id)
                .order_by(PartnerCommission.created_at)
                .all()
            )
            assert len(commissions) == 2
            assert commissions[0].status == CommissionStatus.pending
            assert commissions[0].mature_at > datetime.utcnow() + timedelta(days=1)
            assert commissions[1].status == CommissionStatus.available
            assert commissions[1].mature_at <= datetime.utcnow()
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_commission_idempotent_on_stripe_ref():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer = _make_upgraded_partner(db, 2)
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            inv = _invoice(referee_cid, amount_paid=1000, invoice_id="in_fixed_partner_test")
            _handle_invoice_paid(inv, db)
            _handle_invoice_paid(inv, db)  # webhook retry — identical id

            commissions = db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).all()
            assert len(commissions) == 1
        finally:
            cleanup(db, referrer, referee); db.close()

    test("First commission per referee is held (~60d); renewals mature immediately", test_first_commission_held_second_matures_immediately)
    test("Commission accrual is idempotent on stripe_ref (webhook retry)",           test_commission_idempotent_on_stripe_ref)

    # -- Tier auto-upgrade & manual grants ------------------------------------

    def test_tier_upgrades_after_3_paid_referrals():
        init_db()
        db = SessionLocal()
        referrer = None
        referees = []
        try:
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=_stripe_id())  # starts Tier 1
            for _ in range(2):  # 2 already-paid referrals (below the threshold of 3)
                r = make_user(db)
                referees.append(r)
                db.add(Referral(referrer_id=referrer.id, referee_id=r.id,
                                 status=ReferralStatus.subscribed, sub_credited=True))
            db.commit()

            referee_cid = _stripe_id()
            referee_sid = _sub_id()
            new_referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referees.append(new_referee)
            new_referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=new_referee.id))
            db.commit()

            with patch("billing.stripe.Customer.create_balance_transaction"):
                _sync_subscription(_FakeStripeObject({
                    "id": referee_sid, "customer": referee_cid, "status": "active",
                    "cancel_at_period_end": False, "cancel_at": None, "trial_end": None,
                }), db)

            db.refresh(referrer)
            assert referrer.partner_tier == 2
            assert referrer.partner_status == "active"
        finally:
            cleanup(db, referrer, *referees); db.close()

    def test_manual_tier3_not_downgraded():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer = _make_upgraded_partner(db, 3, manual=True)  # manual Tier 3, no paid referrals
            referee_cid = _stripe_id()
            referee_sid = _sub_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            with patch("billing.stripe.Customer.create_balance_transaction"):
                _sync_subscription(_FakeStripeObject({
                    "id": referee_sid, "customer": referee_cid, "status": "active",
                    "cancel_at_period_end": False, "cancel_at": None, "trial_end": None,
                }), db)

            db.refresh(referrer)
            assert referrer.partner_tier == 3  # manual grant is sticky
        finally:
            cleanup(db, referrer, referee); db.close()

    test("Partner auto-upgrades to Tier 2 at 3 paid referrals", test_tier_upgrades_after_3_paid_referrals)
    test("Manual Tier 3 is never auto-downgraded",              test_manual_tier3_not_downgraded)

    import config as _cfg
    if _cfg.AUTHOR_PASSWORD:
        def test_admin_grant_tier_sets_manual():
            init_db()
            db = SessionLocal()
            target = None
            try:
                target = make_user(db, AccountLevel.unlimited, stripe_id=_stripe_id())
                r = client.post("/partner/admin/tier", data={"email": target.email, "tier": "3"},
                                auth=("cjcol01", _cfg.AUTHOR_PASSWORD), follow_redirects=False)
                assert r.status_code in (302, 303, 307)
                db.refresh(target)
                assert target.partner_tier == 3
                assert target.partner_tier_manual is True
                assert target.partner_status == "active"
            finally:
                cleanup(db, target); db.close()
        test("Admin manual tier grant sets sticky manual flag", test_admin_grant_tier_sets_manual)
    else:
        skip("Admin manual tier grant sets sticky manual flag", "AUTHOR_PASSWORD not set")

    # -- Dashboard ------------------------------------------------------------

    def test_dashboard_open_to_all():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/partner/dashboard", cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 200
        finally:
            delete_by_name(uname)

    def test_dashboard_requires_auth():
        r = client.get("/partner/dashboard", follow_redirects=False)
        assert r.status_code in (302, 307)

    def test_dashboard_shows_matured_balance():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer = _make_upgraded_partner(db, 2)
            referee = make_user(db, AccountLevel.trial)
            db.add(PartnerCommission(
                partner_id=referrer.id, referee_id=referee.id,
                source_amount_pence=1000, rate_bps=1500, amount_pence=150,
                kind="subscription", stripe_ref=f"in_{_sec.token_hex(4)}",
                status=CommissionStatus.pending,
                mature_at=datetime.utcnow() - timedelta(days=1),  # already matured
            ))
            db.commit()
            token = create_token(referrer.id)
            r = client.get("/partner/dashboard", cookies={"session": token})
            assert r.status_code == 200
            assert "1.50" in r.text
        finally:
            cleanup(db, referrer, referee); db.close()

    test("/partner/dashboard is open to every user",             test_dashboard_open_to_all)
    test("/partner/dashboard requires auth",                     test_dashboard_requires_auth)
    test("/partner/dashboard shows matured balance as available", test_dashboard_shows_matured_balance)

    # -- Withdrawals ----------------------------------------------------------

    def _give_available_balance(db, partner, referee, pence):
        db.add(PartnerCommission(
            partner_id=partner.id, referee_id=referee.id,
            source_amount_pence=pence, rate_bps=0, amount_pence=pence,
            kind="referral_flat", stripe_ref=f"cs_{_sec.token_hex(4)}",
            status=CommissionStatus.pending,
            mature_at=datetime.utcnow() - timedelta(days=1),  # matured → available
        ))
        db.commit()

    def test_withdraw_below_threshold_rejected():
        init_db()
        db = SessionLocal()
        partner = referee = None
        try:
            partner = make_user(db, AccountLevel.unlimited, stripe_id=_stripe_id())
            referee = make_user(db, AccountLevel.trial)
            _give_available_balance(db, partner, referee, PARTNER_WITHDRAWAL_THRESHOLD_PENCE - 100)
            token = create_token(partner.id)
            r = client.post("/partner/withdraw", cookies={"session": token},
                            data={"method": "paypal", "destination": "me@example.com"},
                            follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "withdraw_error=below_threshold" in r.headers.get("location", "")
            assert db.query(Withdrawal).filter(Withdrawal.partner_id == partner.id).count() == 0
        finally:
            cleanup(db, partner, referee); db.close()

    def test_withdraw_at_threshold_creates_request():
        init_db()
        db = SessionLocal()
        partner = referee = None
        try:
            partner = make_user(db, AccountLevel.unlimited, stripe_id=_stripe_id())
            referee = make_user(db, AccountLevel.trial)
            _give_available_balance(db, partner, referee, PARTNER_WITHDRAWAL_THRESHOLD_PENCE)
            token = create_token(partner.id)
            r = client.post("/partner/withdraw", cookies={"session": token},
                            data={"method": "bank", "destination": "12-34-56 / 12345678"},
                            follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "withdraw_success=1" in r.headers.get("location", "")
            w = db.query(Withdrawal).filter(Withdrawal.partner_id == partner.id).first()
            assert w is not None
            assert w.amount_pence == PARTNER_WITHDRAWAL_THRESHOLD_PENCE
            assert w.status == WithdrawalStatus.requested
            # A pending request holds the balance, so it can't be double-withdrawn.
            from server import _partner_balance
            assert _partner_balance(partner, db)["available_pence"] == 0
        finally:
            cleanup(db, partner, referee); db.close()

    test("Withdraw below £20 threshold is rejected",   test_withdraw_below_threshold_rejected)
    test("Withdraw at threshold creates a request and holds balance", test_withdraw_at_threshold_creates_request)

    # -- Admin ----------------------------------------------------------------

    def test_admin_requires_basic_auth():
        r = client.get("/partner/admin")
        assert r.status_code == 401

    test("/partner/admin requires HTTP Basic auth", test_admin_requires_basic_auth)
