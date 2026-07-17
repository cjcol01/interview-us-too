"""
Partner (affiliate) programme tests — eligibility/join, commission accrual,
tier upgrades, the first-payment hold, webhook idempotency, and the dashboard.
"""
import secrets as _sec
from datetime import datetime, timedelta
from unittest.mock import patch

from auth import create_token
from database import SessionLocal, init_db
from models import AccountLevel, CommissionStatus, PartnerCommission, Referral, ReferralStatus, User
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


def register(test, skip, client):
    from billing import _handle_invoice_paid, _handle_sessions_purchase, _sync_subscription

    # -- Eligibility & join ---------------------------------------------------

    def test_join_rejected_below_threshold():
        init_db()
        db = SessionLocal()
        referrer = referees = None
        try:
            referrer = make_user(db, AccountLevel.unlimited)
            token = create_token(referrer.id)
            referees = [make_user(db) for _ in range(2)]  # below PARTNER_JOIN_MIN_SIGNUPS (3)
            for ref in referees:
                db.add(Referral(referrer_id=referrer.id, referee_id=ref.id))
            db.commit()
            r = client.post("/partner/join", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            db.refresh(referrer)
            assert referrer.partner_status != "active"
        finally:
            cleanup(db, referrer, *(referees or [])); db.close()

    def test_join_accepted_at_threshold():
        init_db()
        db = SessionLocal()
        referrer = referees = None
        try:
            referrer = make_user(db, AccountLevel.unlimited)
            token = create_token(referrer.id)
            referees = [make_user(db) for _ in range(3)]
            for ref in referees:
                db.add(Referral(referrer_id=referrer.id, referee_id=ref.id))
            db.commit()
            r = client.post("/partner/join", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/partner/dashboard" in r.headers.get("location", "")
            db.refresh(referrer)
            assert referrer.partner_status == "active"
            assert referrer.partner_tier == 1
        finally:
            cleanup(db, referrer, *(referees or [])); db.close()

    def test_join_requires_auth():
        r = client.post("/partner/join", follow_redirects=False)
        assert r.status_code in (302, 303, 307, 401, 403)

    test("POST /partner/join rejected below 3 signups",           test_join_rejected_below_threshold)
    test("POST /partner/join accepted at 3 signups → Tier 1",     test_join_accepted_at_threshold)
    test("POST /partner/join requires auth",                      test_join_requires_auth)

    # -- Commission accrual ---------------------------------------------------

    def test_partner_earns_commission_on_intro_purchase():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referrer.partner_status = "active"
            referrer.partner_tier = 1
            db.commit()
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            data = _checkout_data(referee_cid, "sessions", amount_total=200)
            with patch("billing.stripe.Customer.create_balance_transaction") as mock_credit:
                _handle_sessions_purchase(data, db)

            mock_credit.assert_not_called()  # partner skips the flat credit
            commission = db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first()
            assert commission is not None
            assert commission.amount_pence == 30  # 15% of 200p
            assert commission.kind == "intro"
            assert commission.status == CommissionStatus.pending
            assert commission.mature_at > datetime.utcnow() + timedelta(days=59)
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_non_partner_still_gets_flat_credit_no_commission():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            data = _checkout_data(referee_cid, "sessions", amount_total=200)
            with patch("billing.stripe.Customer.create_balance_transaction") as mock_credit:
                _handle_sessions_purchase(data, db)

            mock_credit.assert_called_once()
            assert db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first() is None
            db.refresh(referrer)
            assert referrer.referral_credit_pence == 200
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_partner_earns_commission_on_subscription_invoice():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referrer.partner_status = "active"
            referrer.partner_tier = 1
            db.commit()
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            _handle_invoice_paid(_invoice(referee_cid, amount_paid=1000), db)
            commissions = db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).all()
            assert len(commissions) == 1
            assert commissions[0].amount_pence == 150  # 15% of 1000p
            assert commissions[0].kind == "subscription"
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_tier2_rate_applied():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referrer.partner_status = "active"
            referrer.partner_tier = 2
            db.commit()
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=referee.id))
            db.commit()

            _handle_invoice_paid(_invoice(referee_cid, amount_paid=1000), db)
            commission = db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first()
            assert commission.amount_pence == 250  # 25% of 1000p
            assert commission.rate_bps == 2500
        finally:
            cleanup(db, referrer, referee); db.close()

    test("Partner earns commission on intro purchase, no flat credit", test_partner_earns_commission_on_intro_purchase)
    test("Non-partner keeps flat credit, no commission row",           test_non_partner_still_gets_flat_credit_no_commission)
    test("Partner earns commission on subscription invoice",           test_partner_earns_commission_on_subscription_invoice)
    test("Tier 2 partner earns 25% instead of 15%",                    test_tier2_rate_applied)

    # -- Hold rule & renewals --------------------------------------------------

    def test_first_commission_held_second_matures_immediately():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referrer.partner_status = "active"
            referrer.partner_tier = 1
            db.commit()
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
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referrer.partner_status = "active"
            referrer.partner_tier = 1
            db.commit()
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

    # -- Tier auto-upgrade ------------------------------------------------------

    def test_tier_upgrades_after_15_paid_referrals():
        init_db()
        db = SessionLocal()
        referrer = None
        referees = []
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referrer.partner_status = "active"
            referrer.partner_tier = 1
            db.commit()

            for _ in range(14):
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
        finally:
            cleanup(db, referrer, *referees); db.close()

    test("Partner auto-upgrades to Tier 2 at 15 paid referrals", test_tier_upgrades_after_15_paid_referrals)

    # -- Dashboard --------------------------------------------------------------

    def test_dashboard_redirects_non_partner():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/partner/dashboard", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert r.headers.get("location", "").endswith("/partner")
        finally:
            delete_by_name(uname)

    def test_dashboard_requires_auth():
        r = client.get("/partner/dashboard", follow_redirects=False)
        assert r.status_code in (302, 307)

    def test_dashboard_shows_balances_for_partner():
        init_db()
        db = SessionLocal()
        referrer = referee = None
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referrer.partner_status = "active"
            referrer.partner_tier = 1
            db.commit()
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

    test("/partner/dashboard redirects non-partners to /partner", test_dashboard_redirects_non_partner)
    test("/partner/dashboard requires auth",                      test_dashboard_requires_auth)
    test("/partner/dashboard shows matured balance as available", test_dashboard_shows_balances_for_partner)

    # -- Admin --------------------------------------------------------------

    def test_admin_requires_basic_auth():
        r = client.get("/partner/admin")
        assert r.status_code == 401

    test("/partner/admin requires HTTP Basic auth", test_admin_requires_basic_auth)
