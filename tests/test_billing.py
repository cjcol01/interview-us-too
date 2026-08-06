"""
Billing tests — split into:
  register()      unit tests (DB logic, no HTTP client needed)
  register_http() route tests (require TestClient)
"""
import secrets as _sec
from unittest.mock import MagicMock, patch

from database import SessionLocal, init_db
from models import AccountLevel, IntroCardFingerprint, PartnerCommission, Referral, ReferralStatus, User
from tests.helpers import cleanup, delete_by_name, make_cookie, make_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeStripeObject(dict):
    """Mimics the real stripe.StripeObject's .to_dict() so mocked
    stripe.Webhook.construct_event() results work with handle_webhook_event(),
    which calls event["data"]["object"].to_dict()."""
    def to_dict(self):
        return dict(self)

def _stripe_id():
    return f"cus_test_{_sec.token_hex(6)}"

def _sub_id():
    return f"sub_test_{_sec.token_hex(6)}"

def _fake_sub(customer_id, sub_id, status="active", cancel_at_period_end=False):
    return _FakeStripeObject({
        "id": sub_id,
        "customer": customer_id,
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "cancel_at": None,
        "trial_end": None,
    })

def _fake_checkout_event(customer_id, plan, payment_intent="pi_test"):
    return {
        "type": "checkout.session.completed",
        "data": {"object": _FakeStripeObject({
            "customer": customer_id,
            "mode": "payment",
            "payment_intent": payment_intent,
            "metadata": {"plan": plan},
        })},
    }


# ---------------------------------------------------------------------------
# Unit tests (no HTTP client)
# ---------------------------------------------------------------------------

def register(test, skip, client=None):
    from billing import _handle_sessions_purchase, _handle_invoice_paid, _sync_subscription, create_checkout_session

    # -- _sync_subscription --------------------------------------------------

    def test_sync_active_sets_unlimited():
        init_db()
        db = SessionLocal()
        try:
            cid, sid = _stripe_id(), _sub_id()
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            _sync_subscription(_fake_sub(cid, sid, "active"), db)
            db.refresh(u)
            assert u.account_level == AccountLevel.unlimited
            assert u.stripe_sub_id == sid
        finally:
            cleanup(db, u); db.close()

    def test_sync_trialing_sets_unlimited():
        init_db()
        db = SessionLocal()
        try:
            cid, sid = _stripe_id(), _sub_id()
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            _sync_subscription(_fake_sub(cid, sid, "trialing"), db)
            db.refresh(u)
            assert u.account_level == AccountLevel.unlimited
        finally:
            cleanup(db, u); db.close()

    def test_sync_canceled_sets_free():
        init_db()
        db = SessionLocal()
        try:
            cid, sid = _stripe_id(), _sub_id()
            u = make_user(db, AccountLevel.unlimited, stripe_id=cid)
            u.stripe_sub_id = sid
            db.commit()
            _sync_subscription(_fake_sub(cid, sid, "canceled"), db)
            db.refresh(u)
            assert u.account_level == AccountLevel.free
        finally:
            cleanup(db, u); db.close()

    def test_sync_unknown_customer_is_noop():
        init_db()
        db = SessionLocal()
        try:
            _sync_subscription(_fake_sub("cus_nonexistent", _sub_id(), "active"), db)
        finally:
            db.close()

    # -- _handle_sessions_purchase -------------------------------------------

    def test_sessions_purchase_grants_1_session():
        init_db()
        db = SessionLocal()
        try:
            cid = _stripe_id()
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            data = _fake_checkout_event(cid, "sessions")["data"]["object"]
            _handle_sessions_purchase(data, db)
            db.refresh(u)
            assert u.sessions_remaining == 1
            assert u.intro_redeemed is True
        finally:
            cleanup(db, u); db.close()

    def test_sessions_pack_grants_3_sessions():
        init_db()
        db = SessionLocal()
        try:
            cid = _stripe_id()
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            data = _fake_checkout_event(cid, "sessions_pack")["data"]["object"]
            _handle_sessions_purchase(data, db)
            db.refresh(u)
            assert u.sessions_remaining == 3
        finally:
            cleanup(db, u); db.close()

    def test_sessions_purchase_unknown_plan_is_noop():
        init_db()
        db = SessionLocal()
        try:
            cid = _stripe_id()
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            data = _fake_checkout_event(cid, "unknown_plan")["data"]["object"]
            _handle_sessions_purchase(data, db)
            db.refresh(u)
            assert u.sessions_remaining == 0
        finally:
            cleanup(db, u); db.close()

    def test_sessions_purchase_no_user_is_noop():
        init_db()
        db = SessionLocal()
        try:
            data = _fake_checkout_event("cus_nobody", "sessions")["data"]["object"]
            _handle_sessions_purchase(data, db)
        finally:
            db.close()

    # -- Card-fingerprint fraud dedup (_get_card_fingerprint / IntroCardFingerprint) --
    # The dedup branch only runs for a non-test (live) Stripe key, so these tests patch
    # billing.STRIPE_SECRET_KEY to a fake live-shaped value to exercise it.

    def test_sessions_purchase_duplicate_fingerprint_refunds_and_declines():
        init_db()
        db = SessionLocal()
        fp = f"fp_test_{_sec.token_hex(6)}"
        try:
            db.add(IntroCardFingerprint(fingerprint=fp))
            db.commit()
            cid = _stripe_id()
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            data = _fake_checkout_event(cid, "sessions", payment_intent="pi_dup")["data"]["object"]
            with patch("billing.STRIPE_SECRET_KEY", "sk_live_fake"), \
                 patch("billing._get_card_fingerprint", return_value=fp), \
                 patch("billing.stripe.Refund.create") as mock_refund:
                _handle_sessions_purchase(data, db)
            mock_refund.assert_called_once_with(payment_intent="pi_dup")
            db.refresh(u)
            assert u.intro_declined is True
            assert u.sessions_remaining == 0
            assert u.intro_redeemed is False
        finally:
            db.query(IntroCardFingerprint).filter(IntroCardFingerprint.fingerprint == fp).delete()
            cleanup(db, u); db.close()

    def test_sessions_purchase_fresh_fingerprint_records_and_grants():
        init_db()
        db = SessionLocal()
        fp = f"fp_test_{_sec.token_hex(6)}"
        try:
            cid = _stripe_id()
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            data = _fake_checkout_event(cid, "sessions", payment_intent="pi_fresh")["data"]["object"]
            with patch("billing.STRIPE_SECRET_KEY", "sk_live_fake"), \
                 patch("billing._get_card_fingerprint", return_value=fp), \
                 patch("billing.stripe.Refund.create") as mock_refund:
                _handle_sessions_purchase(data, db)
            mock_refund.assert_not_called()
            db.refresh(u)
            assert u.intro_declined is False
            assert u.sessions_remaining == 1
            assert db.query(IntroCardFingerprint).filter(IntroCardFingerprint.fingerprint == fp).first() is not None
        finally:
            db.query(IntroCardFingerprint).filter(IntroCardFingerprint.fingerprint == fp).delete()
            cleanup(db, u); db.close()

    # -- Referral credit on intro purchase -----------------------------------

    def test_no_referrer_reward_on_intro():
        init_db()
        db = SessionLocal()
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            ref_row = Referral(referrer_id=referrer.id, referee_id=referee.id)
            db.add(ref_row)
            db.commit()

            data = _fake_checkout_event(referee_cid, "sessions")["data"]["object"]
            with patch("billing.stripe.Customer.create_balance_transaction") as mock_credit:
                _handle_sessions_purchase(data, db)

            # The intro never pays the referrer — only a real paid plan does.
            mock_credit.assert_not_called()
            assert db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first() is None
            db.refresh(ref_row)
            assert ref_row.intro_credited is True
            assert ref_row.status == ReferralStatus.intro
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_no_double_credit_intro():
        init_db()
        db = SessionLocal()
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            ref_row = Referral(referrer_id=referrer.id, referee_id=referee.id,
                               intro_credited=True, status=ReferralStatus.intro)
            db.add(ref_row)
            db.commit()

            data = _fake_checkout_event(referee_cid, "sessions")["data"]["object"]
            with patch("billing.stripe.Customer.create_balance_transaction") as mock_credit:
                _handle_sessions_purchase(data, db)

            mock_credit.assert_not_called()
        finally:
            cleanup(db, referrer, referee); db.close()

    # -- Referral credit on subscription ------------------------------------

    def test_referrer_credit_reward_on_subscription():
        init_db()
        db = SessionLocal()
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referee_cid = _stripe_id()
            referee_sid = _sub_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            ref_row = Referral(referrer_id=referrer.id, referee_id=referee.id)
            db.add(ref_row)
            db.commit()

            with patch("billing.stripe.Customer.create_balance_transaction") as mock_credit:
                _sync_subscription(_fake_sub(referee_cid, referee_sid, "active"), db)

            # Tier-1 referrer earns a flat £5 as account credit (mirrored to Stripe balance) —
            # no withdrawable PartnerCommission row.
            mock_credit.assert_called_once()
            db.refresh(referrer)
            assert referrer.referral_credit_pence == 500
            assert db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first() is None
            db.refresh(ref_row)
            assert ref_row.sub_credited is True
            assert ref_row.status == ReferralStatus.subscribed
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_no_double_credit_subscription():
        init_db()
        db = SessionLocal()
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referee_cid = _stripe_id()
            referee_sid = _sub_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            ref_row = Referral(referrer_id=referrer.id, referee_id=referee.id,
                               sub_credited=True, status=ReferralStatus.subscribed)
            db.add(ref_row)
            db.commit()

            with patch("billing.stripe.Customer.create_balance_transaction") as mock_credit:
                _sync_subscription(_fake_sub(referee_cid, referee_sid, "active"), db)

            mock_credit.assert_not_called()
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_credit_referrer_skips_if_no_stripe_customer():
        from billing import _credit_referrer
        init_db()
        db = SessionLocal()
        try:
            referrer = make_user(db)
            referrer.stripe_customer_id = None
            db.commit()
            with patch("billing.stripe.Customer.create_balance_transaction") as mock_credit:
                _credit_referrer(referrer, 200, "test")
            mock_credit.assert_not_called()
        finally:
            cleanup(db, referrer); db.close()

    # -- #1: credit only on active, not trialing --------------------------------

    def test_trialing_does_not_credit_referrer():
        init_db()
        db = SessionLocal()
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referee_cid = _stripe_id()
            referee_sid = _sub_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            ref_row = Referral(referrer_id=referrer.id, referee_id=referee.id)
            db.add(ref_row)
            db.commit()

            with patch("billing.stripe.Customer.create_balance_transaction") as mock_credit:
                _sync_subscription(_fake_sub(referee_cid, referee_sid, "trialing"), db)

            mock_credit.assert_not_called()
            db.refresh(ref_row)
            assert ref_row.sub_credited is False
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_trialing_then_active_rewards_once():
        init_db()
        db = SessionLocal()
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referee_cid = _stripe_id()
            referee_sid = _sub_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            ref_row = Referral(referrer_id=referrer.id, referee_id=referee.id)
            db.add(ref_row)
            db.commit()

            with patch("billing.stripe.Customer.create_balance_transaction"):
                _sync_subscription(_fake_sub(referee_cid, referee_sid, "trialing"), db)
                _sync_subscription(_fake_sub(referee_cid, referee_sid, "active"), db)

            # Trialing pays nothing; the single activation earns exactly one £5 credit, once.
            db.refresh(referrer)
            assert referrer.referral_credit_pence == 500
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_sub_trial_used_set_after_subscription():
        init_db()
        db = SessionLocal()
        try:
            cid, sid = _stripe_id(), _sub_id()
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            assert u.sub_trial_used is False
            _sync_subscription(_fake_sub(cid, sid, "trialing"), db)
            db.refresh(u)
            assert u.sub_trial_used is True
        finally:
            cleanup(db, u); db.close()

    # -- #3: pack purchase keeps unlimited ------------------------------------

    def test_sessions_pack_does_not_downgrade_unlimited():
        init_db()
        db = SessionLocal()
        try:
            cid = _stripe_id()
            u = make_user(db, AccountLevel.unlimited, stripe_id=cid)
            data = _fake_checkout_event(cid, "sessions_pack")["data"]["object"]
            _handle_sessions_purchase(data, db)
            db.refresh(u)
            assert u.account_level == AccountLevel.unlimited
            assert u.sessions_remaining == 3
        finally:
            cleanup(db, u); db.close()

    # -- #6: DB credit --------------------------------------------------------

    def test_credit_referrer_increments_db_credit():
        from billing import _credit_referrer
        init_db()
        db = SessionLocal()
        try:
            cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=cid)
            assert referrer.referral_credit_pence == 0
            with patch("billing.stripe.Customer.create_balance_transaction"):
                _credit_referrer(referrer, 200, "test")
            assert referrer.referral_credit_pence == 200
        finally:
            cleanup(db, referrer); db.close()

    def test_sessions_purchase_deducts_applied_credit():
        init_db()
        db = SessionLocal()
        try:
            cid = _stripe_id()
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            u.referral_credit_pence = 500
            db.commit()
            data = _fake_checkout_event(cid, "sessions")["data"]["object"]
            data["total_details"] = {"amount_discount": 200}
            with patch("billing.stripe.Customer.create_balance_transaction"):
                _handle_sessions_purchase(data, db)
            db.refresh(u)
            assert u.referral_credit_pence == 300
        finally:
            cleanup(db, u); db.close()

    def test_invoice_paid_deducts_consumed_credit():
        init_db()
        db = SessionLocal()
        try:
            cid = _stripe_id()
            u = make_user(db, AccountLevel.unlimited, stripe_id=cid)
            u.referral_credit_pence = 500
            db.commit()
            fake_invoice = {
                "customer": cid,
                "starting_balance": -500,
                "ending_balance": -200,
            }
            _handle_invoice_paid(fake_invoice, db)
            db.refresh(u)
            assert u.referral_credit_pence == 200
        finally:
            cleanup(db, u); db.close()

    def test_invoice_paid_clamps_at_zero():
        init_db()
        db = SessionLocal()
        try:
            cid = _stripe_id()
            u = make_user(db, AccountLevel.unlimited, stripe_id=cid)
            u.referral_credit_pence = 100
            db.commit()
            fake_invoice = {
                "customer": cid,
                "starting_balance": -500,
                "ending_balance": 0,
            }
            _handle_invoice_paid(fake_invoice, db)
            db.refresh(u)
            assert u.referral_credit_pence == 0
        finally:
            cleanup(db, u); db.close()

    # -- #7: no trial on resubscription ---------------------------------------

    def test_checkout_no_trial_when_sub_trial_used():
        from unittest.mock import MagicMock
        init_db()
        db = SessionLocal()
        try:
            cid = _stripe_id()
            u = make_user(db, AccountLevel.free, stripe_id=cid)
            u.sub_trial_used = True
            db.commit()
            captured = {}
            mock_session = MagicMock()
            mock_session.url = "https://checkout.stripe.com/pay/test"
            def capture_create(**kwargs):
                captured.update(kwargs)
                return mock_session
            with patch("billing.stripe.checkout.Session.create", side_effect=capture_create):
                create_checkout_session(u, db, plan="subscription")
            assert "subscription_data" not in captured, "trial offered again after sub_trial_used"
        finally:
            cleanup(db, u); db.close()

    def test_checkout_trial_when_sub_trial_not_used():
        from unittest.mock import MagicMock
        init_db()
        db = SessionLocal()
        try:
            cid = _stripe_id()
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            assert u.sub_trial_used is False
            captured = {}
            mock_session = MagicMock()
            mock_session.url = "https://checkout.stripe.com/pay/test"
            def capture_create(**kwargs):
                captured.update(kwargs)
                return mock_session
            with patch("billing.stripe.checkout.Session.create", side_effect=capture_create):
                create_checkout_session(u, db, plan="subscription")
            assert "subscription_data" in captured
            assert captured["subscription_data"].get("trial_period_days") == 7
        finally:
            cleanup(db, u); db.close()

    test("_sync_subscription: active → unlimited",               test_sync_active_sets_unlimited)
    test("_sync_subscription: trialing → unlimited",             test_sync_trialing_sets_unlimited)
    test("_sync_subscription: canceled → free",                  test_sync_canceled_sets_free)
    test("_sync_subscription: unknown customer is noop",         test_sync_unknown_customer_is_noop)
    test("Sessions purchase (intro) grants 1 session",           test_sessions_purchase_grants_1_session)
    test("Sessions pack grants 3 sessions",                      test_sessions_pack_grants_3_sessions)
    test("Sessions purchase: unknown plan is noop",              test_sessions_purchase_unknown_plan_is_noop)
    test("Sessions purchase: no user is noop",                   test_sessions_purchase_no_user_is_noop)
    test("Sessions purchase: dup card fingerprint → refund+decline", test_sessions_purchase_duplicate_fingerprint_refunds_and_declines)
    test("Sessions purchase: fresh fingerprint → recorded+granted",  test_sessions_purchase_fresh_fingerprint_records_and_grants)
    test("No referrer reward on referee intro purchase",         test_no_referrer_reward_on_intro)
    test("No double-credit on intro (intro_credited guard)",     test_no_double_credit_intro)
    test("Referrer earns £5 account credit when referee subscribes", test_referrer_credit_reward_on_subscription)
    test("No double-credit on subscription (sub_credited guard)",test_no_double_credit_subscription)
    test("_credit_referrer skips if no Stripe customer",         test_credit_referrer_skips_if_no_stripe_customer)
    def test_referrer_credit_reward_on_sessions_pack():
        init_db()
        db = SessionLocal()
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            ref_row = Referral(referrer_id=referrer.id, referee_id=referee.id)
            db.add(ref_row)
            db.commit()

            data = _fake_checkout_event(referee_cid, "sessions_pack")["data"]["object"]
            with patch("billing.stripe.Customer.create_balance_transaction") as mock_credit:
                _handle_sessions_purchase(data, db)

            # Flat £5 as account credit (the £10 pack is a real paid plan) — no commission row.
            mock_credit.assert_called_once()
            db.refresh(referrer)
            assert referrer.referral_credit_pence == 500
            assert db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first() is None
            db.refresh(ref_row)
            assert ref_row.sub_credited is True
            assert ref_row.status == ReferralStatus.subscribed
        finally:
            cleanup(db, referrer, referee); db.close()

    def test_no_double_reward_sessions_pack():
        init_db()
        db = SessionLocal()
        try:
            referrer_cid = _stripe_id()
            referrer = make_user(db, AccountLevel.unlimited, stripe_id=referrer_cid)
            referee_cid = _stripe_id()
            referee = make_user(db, AccountLevel.trial, stripe_id=referee_cid)
            referee.referred_by_id = referrer.id
            ref_row = Referral(referrer_id=referrer.id, referee_id=referee.id,
                               sub_credited=True, status=ReferralStatus.subscribed)
            db.add(ref_row)
            db.commit()

            data = _fake_checkout_event(referee_cid, "sessions_pack")["data"]["object"]
            with patch("billing.stripe.Customer.create_balance_transaction") as mock_credit:
                _handle_sessions_purchase(data, db)

            mock_credit.assert_not_called()
            assert db.query(PartnerCommission).filter(PartnerCommission.partner_id == referrer.id).first() is None
        finally:
            cleanup(db, referrer, referee); db.close()

    test("Referrer earns £5 account credit on referee sessions pack", test_referrer_credit_reward_on_sessions_pack)
    test("No double reward on sessions pack (sub_credited guard)", test_no_double_reward_sessions_pack)
    test("#1: trialing does NOT reward referrer",                test_trialing_does_not_credit_referrer)
    test("#1: trialing then active rewards referrer once",       test_trialing_then_active_rewards_once)
    test("#7: sub_trial_used set after first subscription",      test_sub_trial_used_set_after_subscription)
    test("#3: pack purchase keeps unlimited account level",      test_sessions_pack_does_not_downgrade_unlimited)
    test("#6: _credit_referrer increments DB credit",            test_credit_referrer_increments_db_credit)
    test("#6: intro purchase deducts applied discount from DB",  test_sessions_purchase_deducts_applied_credit)
    test("#6: invoice.paid deducts consumed balance from DB",    test_invoice_paid_deducts_consumed_credit)
    test("#6: invoice.paid clamps credit at zero",               test_invoice_paid_clamps_at_zero)
    test("#7: checkout omits trial when sub_trial_used=True",    test_checkout_no_trial_when_sub_trial_used)
    test("#7: checkout includes trial when sub_trial_used=False",test_checkout_trial_when_sub_trial_not_used)


# ---------------------------------------------------------------------------
# HTTP route tests (require TestClient)
# ---------------------------------------------------------------------------

def register_http(test, skip, client):

    def test_cancel_requires_auth():
        r = client.get("/billing/cancel", follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    def test_cancel_page_accessible():
        # Unlimited with no Stripe sub (comped/admin account) still reaches the page.
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.unlimited)
        try:
            r = client.get("/billing/cancel", cookies={"session": token})
            assert r.status_code == 200
        finally:
            delete_by_name(uname)

    def test_cancel_page_redirects_without_subscription():
        # Session-pack buyers have no recurring charge to stop — the page would be a lie.
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.paid)
        try:
            r = client.get("/billing/cancel", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert "/settings" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    def test_cancel_confirm_requires_auth():
        r = client.post("/billing/cancel/confirm",
                        data={"reason": "test", "detail": ""},
                        follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    def test_cancel_confirm_no_subscription_returns_400():
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.unlimited)
        try:
            r = client.post("/billing/cancel/confirm",
                            data={"reason": "too expensive", "detail": ""},
                            cookies={"session": token},
                            follow_redirects=False)
            assert r.status_code == 400
        finally:
            delete_by_name(uname)

    def test_cancel_confirm_success():
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.unlimited)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.stripe_sub_id = _sub_id()
            db.commit()
            mock_cancel = MagicMock(return_value=None)
            with patch("server.cancel_subscription", mock_cancel):
                r = client.post("/billing/cancel/confirm",
                                data={"reason": "too expensive", "detail": ""},
                                cookies={"session": token},
                                follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            mock_cancel.assert_called_once()
        finally:
            db.close()
            delete_by_name(uname)

    def test_account_delete_page_requires_auth():
        r = client.get("/account/delete", follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    def test_account_delete_page_accessible():
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.unlimited)
        try:
            r = client.get("/account/delete", cookies={"session": token})
            assert r.status_code == 200
        finally:
            delete_by_name(uname)

    def test_account_delete_confirm_requires_auth():
        r = client.post("/account/delete/confirm",
                        data={"password": "testpass123"},
                        follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    def test_account_delete_confirm_wrong_password_returns_400():
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.post("/account/delete/confirm",
                            data={"password": "wrongpassword", "reason": "other", "detail": ""},
                            cookies={"session": token},
                            follow_redirects=False)
            assert r.status_code == 400
        finally:
            delete_by_name(uname)

    def test_account_delete_confirm_success():
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.unlimited)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.stripe_sub_id = _sub_id()
            db.commit()
            user_id = u.id

            mock_cancel = MagicMock(return_value=None)
            with patch("server.cancel_subscription_immediately", mock_cancel):
                r = client.post("/account/delete/confirm",
                                data={"password": "testpass123", "reason": "privacy", "detail": "test"},
                                cookies={"session": token},
                                follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert r.headers.get("location", "").startswith("/login")
            mock_cancel.assert_called_once()

            db.expire_all()
            assert db.query(User).filter(User.id == user_id).first() is None
        finally:
            db.close()
            delete_by_name(uname)

    def test_portal_requires_auth():
        r = client.post("/billing/portal", follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    def test_webhook_subscription_created():
        cid, sid = _stripe_id(), _sub_id()
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            fake_event = {
                "type": "customer.subscription.created",
                "data": {"object": _fake_sub(cid, sid, "active")},
            }
            with patch("billing.stripe.Webhook.construct_event", return_value=fake_event):
                r = client.post("/billing/webhook", content=b"payload",
                                headers={"stripe-signature": "test"})
            assert r.status_code == 200
            db.refresh(u)
            assert u.account_level == AccountLevel.unlimited
        finally:
            cleanup(db, u); db.close()

    def test_webhook_subscription_deleted():
        cid, sid = _stripe_id(), _sub_id()
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.unlimited, stripe_id=cid)
            u.stripe_sub_id = sid
            db.commit()
            fake_event = {
                "type": "customer.subscription.deleted",
                "data": {"object": _FakeStripeObject({"customer": cid, "id": sid})},
            }
            with patch("billing.stripe.Webhook.construct_event", return_value=fake_event):
                r = client.post("/billing/webhook", content=b"payload",
                                headers={"stripe-signature": "test"})
            assert r.status_code == 200
            db.refresh(u)
            assert u.account_level == AccountLevel.free
            assert u.stripe_sub_id is None
        finally:
            cleanup(db, u); db.close()

    def test_webhook_checkout_sessions_purchase():
        cid = _stripe_id()
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            fake_event = _fake_checkout_event(cid, "sessions")
            with patch("billing.stripe.Webhook.construct_event", return_value=fake_event):
                r = client.post("/billing/webhook", content=b"payload",
                                headers={"stripe-signature": "test"})
            assert r.status_code == 200
            db.refresh(u)
            assert u.sessions_remaining == 1
            assert u.intro_redeemed is True
        finally:
            cleanup(db, u); db.close()

    def test_webhook_invoice_paid_marks_paid():
        cid = _stripe_id()
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.unlimited, stripe_id=cid)
            fake_event = {
                "type": "invoice.paid",
                "data": {"object": _FakeStripeObject({
                    "customer": cid, "amount_paid": 999,
                    "starting_balance": 0, "ending_balance": 0,
                })},
            }
            with patch("billing.stripe.Webhook.construct_event", return_value=fake_event):
                r = client.post("/billing/webhook", content=b"payload",
                                headers={"stripe-signature": "test"})
            assert r.status_code == 200
            db.refresh(u)
            assert u.sub_invoice_paid is True
        finally:
            cleanup(db, u); db.close()

    def test_billing_offer_success_claims_retention():
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.unlimited)
        db = SessionLocal()
        try:
            u = db.query(User).filter(User.username == uname).first()
            u.stripe_sub_id = _sub_id()
            db.commit()
            with patch("billing.stripe.Subscription.modify", return_value=None):
                r = client.post("/billing/offer", cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            assert r.headers["location"] == "/settings?offer=claimed"
            db.refresh(u)
            assert u.retention_offer_claimed is True
        finally:
            db.close(); delete_by_name(uname)

    def test_billing_offer_no_subscription_swallows_error():
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.unlimited)  # no stripe_sub_id set
        db = SessionLocal()
        try:
            r = client.post("/billing/offer", cookies={"session": token}, follow_redirects=False)
            # apply_retention_coupon raises ValueError (no sub) — caught, still redirects cleanly
            assert r.status_code == 303
            u = db.query(User).filter(User.username == uname).first()
            assert u.retention_offer_claimed is False
        finally:
            db.close(); delete_by_name(uname)

    def test_checkout_requires_auth():
        r = client.get("/billing/checkout?plan=subscription", follow_redirects=False)
        assert r.status_code in (302, 307, 401, 403)

    def test_checkout_redirects_to_stripe():
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.trial)
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/pay/test"
        with patch("billing.stripe.checkout.Session.create", return_value=mock_session), \
             patch("billing.stripe.Customer.create", return_value=MagicMock(id=_stripe_id())):
            r = client.get("/billing/checkout?plan=subscription",
                           cookies={"session": token},
                           follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "stripe.com" in r.headers.get("location", "")
        delete_by_name(uname)

    test("GET /billing/cancel requires auth",                 test_cancel_requires_auth)
    test("GET /billing/cancel accessible when authed",        test_cancel_page_accessible)
    test("GET /billing/cancel: no sub → /settings",          test_cancel_page_redirects_without_subscription)
    test("POST /billing/cancel/confirm requires auth",        test_cancel_confirm_requires_auth)
    test("POST /billing/cancel/confirm: no sub → 400",       test_cancel_confirm_no_subscription_returns_400)
    test("POST /billing/cancel/confirm success flow",         test_cancel_confirm_success)
    test("GET /account/delete requires auth",                 test_account_delete_page_requires_auth)
    test("GET /account/delete accessible when authed",        test_account_delete_page_accessible)
    test("POST /account/delete/confirm requires auth",        test_account_delete_confirm_requires_auth)
    test("POST /account/delete/confirm: wrong password → 400", test_account_delete_confirm_wrong_password_returns_400)
    test("POST /account/delete/confirm success flow",         test_account_delete_confirm_success)
    test("POST /billing/portal requires auth",                test_portal_requires_auth)
    test("Webhook: subscription.created sets unlimited",      test_webhook_subscription_created)
    test("Webhook: subscription.deleted sets free",           test_webhook_subscription_deleted)
    test("Webhook: checkout.completed grants sessions",       test_webhook_checkout_sessions_purchase)
    test("Webhook: invoice.paid marks sub_invoice_paid",       test_webhook_invoice_paid_marks_paid)
    test("POST /billing/offer: success claims retention",     test_billing_offer_success_claims_retention)
    test("POST /billing/offer: failure swallowed, still redirects", test_billing_offer_no_subscription_swallows_error)
    test("GET /billing/checkout requires auth",               test_checkout_requires_auth)
    test("GET /billing/checkout redirects to Stripe",         test_checkout_redirects_to_stripe)

    def test_webhook_bad_signature_returns_400():
        import stripe as _stripe
        with patch("billing.stripe.Webhook.construct_event",
                   side_effect=_stripe.error.SignatureVerificationError("bad sig", "sig_header")):
            r = client.post("/billing/webhook", content=b"payload",
                            headers={"stripe-signature": "bogus"})
        assert r.status_code == 400

    def test_webhook_unhandled_event_type_is_noop_200():
        cid = _stripe_id()
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial, stripe_id=cid)
            fake_event = {
                "type": "customer.updated",
                "data": {"object": _FakeStripeObject({"customer": cid})},
            }
            with patch("billing.stripe.Webhook.construct_event", return_value=fake_event):
                r = client.post("/billing/webhook", content=b"payload",
                                headers={"stripe-signature": "test"})
            assert r.status_code == 200
            db.refresh(u)
            assert u.account_level == AccountLevel.trial
        finally:
            cleanup(db, u); db.close()

    test("Webhook: bad signature -> 400",                      test_webhook_bad_signature_returns_400)
    test("Webhook: unhandled event type -> 200 no-op",         test_webhook_unhandled_event_type_is_noop_200)
