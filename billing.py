import stripe
from datetime import datetime
from sqlalchemy.orm import Session

from analytics import logger, track
from config import BASE_URL, STRIPE_PRICE_ID, STRIPE_REFERRAL_COUPON_ID, STRIPE_RETENTION_COUPON_ID, STRIPE_SECRET_KEY, STRIPE_SESSIONS_PACK_PRICE_ID, STRIPE_SESSIONS_PRICE_ID, STRIPE_SUB_PRICE_ID, STRIPE_WEBHOOK_SECRET
from models import AccountLevel, IntroCardFingerprint, Referral, ReferralStatus, User

stripe.api_key = STRIPE_SECRET_KEY


def get_or_create_customer(user: User, db: Session) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(email=user.email, name=user.full_name)
    user.stripe_customer_id = customer.id
    db.commit()
    return customer.id


def _credit_referrer(referrer: User, amount_pence: int, description: str) -> None:
    """Increment DB credit (source of truth) and mirror into Stripe balance for auto-invoice deduction."""
    referrer.referral_credit_pence += amount_pence  # caller commits
    if not referrer.stripe_customer_id:
        logger.warning("[referral] referrer %s has no Stripe customer — skipping balance mirror", referrer.email)
        return
    try:
        stripe.Customer.create_balance_transaction(
            referrer.stripe_customer_id,
            amount=-amount_pence,
            currency="gbp",
            description=description,
        )
        logger.info("[referral] credited %s %dp: %s", referrer.email, amount_pence, description)
    except stripe.error.StripeError as e:
        logger.error("[referral] Stripe balance mirror failed for %s: %s", referrer.email, e)


def apply_retention_coupon(user: User) -> None:
    if not user.stripe_sub_id:
        raise ValueError("No active subscription found.")
    if not STRIPE_RETENTION_COUPON_ID:
        logger.info("[retention] STRIPE_RETENTION_COUPON_ID not configured — skipping coupon")
        return
    key = "promotion_code" if STRIPE_RETENTION_COUPON_ID.startswith("promo_") else "coupon"
    stripe.Subscription.modify(user.stripe_sub_id, discounts=[{key: STRIPE_RETENTION_COUPON_ID}])
    logger.info("[retention] applied retention coupon to sub=%s", user.stripe_sub_id)


def _create_credit_coupon(amount_pence: int) -> str:
    """Create a single-use, amount-off coupon in Stripe for the given pence value. Returns coupon id."""
    coupon = stripe.Coupon.create(
        amount_off=amount_pence,
        currency="gbp",
        duration="once",
        max_redemptions=1,
    )
    return coupon.id


def create_checkout_session(user: User, db: Session, plan: str = "subscription", apply_referral_discount: bool = False) -> str:
    customer_id = get_or_create_customer(user, db)

    if plan == "sessions":
        kwargs = dict(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_SESSIONS_PRICE_ID, "quantity": 1}],
            mode="payment",
            metadata={"plan": "sessions"},
            success_url=f"{BASE_URL}/billing/success",
            cancel_url=f"{BASE_URL}/pricing",
        )
        if user.referral_credit_pence > 0:
            kwargs["discounts"] = [{"coupon": _create_credit_coupon(user.referral_credit_pence)}]
        session = stripe.checkout.Session.create(**kwargs)

    elif plan == "sessions_pack":
        kwargs = dict(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_SESSIONS_PACK_PRICE_ID, "quantity": 1}],
            mode="payment",
            metadata={"plan": "sessions_pack"},
            success_url=f"{BASE_URL}/billing/success",
            cancel_url=f"{BASE_URL}/pricing",
        )
        if user.referral_credit_pence > 0:
            kwargs["discounts"] = [{"coupon": _create_credit_coupon(user.referral_credit_pence)}]
        session = stripe.checkout.Session.create(**kwargs)

    else:
        kwargs = dict(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_SUB_PRICE_ID or STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            success_url=f"{BASE_URL}/billing/success",
            cancel_url=f"{BASE_URL}/pricing",
        )
        if not user.sub_trial_used:
            kwargs["subscription_data"] = {"trial_period_days": 7}
        if apply_referral_discount and STRIPE_REFERRAL_COUPON_ID:
            key = "promotion_code" if STRIPE_REFERRAL_COUPON_ID.startswith("promo_") else "coupon"
            kwargs["discounts"] = [{key: STRIPE_REFERRAL_COUPON_ID}]
        session = stripe.checkout.Session.create(**kwargs)

    return session.url


def cancel_subscription(user: User) -> datetime | None:
    if not user.stripe_sub_id:
        raise ValueError("No active subscription found.")
    stripe.Subscription.modify(user.stripe_sub_id, cancel_at_period_end=True)
    sub = stripe.Subscription.retrieve(user.stripe_sub_id)
    period_end = sub.get("cancel_at") or sub.get("trial_end")
    return datetime.utcfromtimestamp(period_end) if period_end else None


def create_portal_session(user: User) -> str:
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{BASE_URL}/settings",
    )
    return session.url


def handle_webhook_event(payload: bytes, sig_header: str, db: Session):
    event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    data = event["data"]["object"]

    if event["type"] in ("customer.subscription.created", "customer.subscription.updated"):
        _sync_subscription(data, db)

    elif event["type"] == "customer.subscription.deleted":
        user = db.query(User).filter(User.stripe_customer_id == data["customer"]).first()
        if user:
            user.account_level = AccountLevel.free
            user.stripe_sub_id = None
            db.commit()

    elif event["type"] == "checkout.session.completed":
        if data.get("mode") == "payment":
            _handle_sessions_purchase(data, db)

    elif event["type"] == "invoice.paid":
        _handle_invoice_paid(data, db)


def _sync_subscription(sub: dict, db: Session):
    user = db.query(User).filter(User.stripe_customer_id == sub["customer"]).first()
    if not user:
        return
    user.stripe_sub_id = sub["id"]
    if sub["status"] in ("active", "trialing"):
        user.account_level = AccountLevel.unlimited
        user.sub_trial_used = True
        period_end = sub.get("cancel_at") or sub.get("trial_end")
        if sub.get("cancel_at_period_end") and period_end:
            user.sub_cancel_at = datetime.utcfromtimestamp(period_end)
        elif not sub.get("cancel_at_period_end"):
            user.sub_cancel_at = None
        # Only credit the referrer once the referee has actually paid (active, not trialing)
        if sub["status"] == "active" and user.referred_by_id:
            ref = db.query(Referral).filter(
                Referral.referee_id == user.id,
                Referral.sub_credited == False,  # noqa: E712
            ).first()
            if ref:
                referrer = db.query(User).filter(User.id == ref.referrer_id).first()
                if referrer:
                    credit = 300 if ref.intro_credited else 500
                    _credit_referrer(referrer, credit, f"Referral — {user.email} subscribed")
                    ref.sub_credited = True
                    ref.status = ReferralStatus.subscribed
                    ref.sub_at = datetime.utcnow()
        track(user.id, "subscription_created", via_referral=bool(user.referred_by_id))
    elif sub["status"] in ("canceled", "unpaid", "incomplete_expired"):
        user.account_level = AccountLevel.free
        user.sub_cancel_at = None
        track(user.id, "subscription_lapsed", status=sub["status"])
    db.commit()


def _get_card_fingerprint(checkout_data: dict) -> str | None:
    payment_intent_id = checkout_data.get("payment_intent")
    if not payment_intent_id:
        return None
    try:
        pi = stripe.PaymentIntent.retrieve(payment_intent_id, expand=["payment_method"])
        pm = pi.payment_method
        if pm and hasattr(pm, "card") and pm.card:
            return pm.card.fingerprint
    except stripe.error.StripeError:
        pass
    return None


def _handle_sessions_purchase(data: dict, db: Session):
    customer_id = data.get("customer")
    logger.info("[webhook] sessions purchase: customer=%s metadata=%s", customer_id, data.get("metadata"))
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        logger.warning("[webhook] no user found for customer %s", customer_id)
        return
    plan = (data.get("metadata") or {}).get("plan", "")
    logger.info("[webhook] user=%s plan=%r sessions_remaining=%d", user.email, plan, user.sessions_remaining)

    if plan == "sessions":
        if not STRIPE_SECRET_KEY.startswith("sk_test_"):
            fingerprint = _get_card_fingerprint(data)
            if fingerprint:
                already_used = db.query(IntroCardFingerprint).filter(
                    IntroCardFingerprint.fingerprint == fingerprint
                ).first()
                if already_used:
                    logger.warning("[webhook] fingerprint already used — refunding user=%s", user.email)
                    payment_intent = data.get("payment_intent")
                    if payment_intent:
                        try:
                            stripe.Refund.create(payment_intent=payment_intent)
                        except stripe.error.StripeError:
                            pass
                    user.intro_declined = True
                    db.commit()
                    return
                db.add(IntroCardFingerprint(fingerprint=fingerprint))
        user.sessions_remaining += 3
        user.intro_redeemed = True
        if user.referred_by_id:
            ref = db.query(Referral).filter(
                Referral.referee_id == user.id,
                Referral.intro_credited == False,  # noqa: E712
            ).first()
            if ref:
                referrer = db.query(User).filter(User.id == ref.referrer_id).first()
                if referrer:
                    _credit_referrer(referrer, 200, f"Referral — {user.email} bought intro")
                    ref.intro_credited = True
                    ref.status = ReferralStatus.intro
                    ref.intro_at = datetime.utcnow()
        track(user.id, "sessions_purchased", plan="sessions", sessions_added=3)

    elif plan == "sessions_pack":
        user.sessions_remaining += 3
        if user.referred_by_id:
            ref = db.query(Referral).filter(
                Referral.referee_id == user.id,
                Referral.sub_credited == False,  # noqa: E712
            ).first()
            if ref:
                referrer = db.query(User).filter(User.id == ref.referrer_id).first()
                if referrer:
                    credit = 300 if ref.intro_credited else 500
                    _credit_referrer(referrer, credit, f"Referral — {user.email} bought sessions pack")
                    ref.sub_credited = True
                    ref.status = ReferralStatus.subscribed
                    ref.sub_at = datetime.utcnow()
        track(user.id, "sessions_purchased", plan="sessions_pack", sessions_added=3)

    else:
        logger.warning("[webhook] unrecognised plan %r — ignoring", plan)
        return

    # Deduct any referral credit that was applied at checkout via coupon
    applied = (data.get("total_details") or {}).get("amount_discount", 0)
    if applied > 0 and user.referral_credit_pence > 0:
        user.referral_credit_pence = max(0, user.referral_credit_pence - applied)
        # Re-sync Stripe balance: the credit was consumed by a payment (not an invoice),
        # so Stripe balance wasn't touched — add it back to cancel the mirror.
        if user.stripe_customer_id:
            try:
                stripe.Customer.create_balance_transaction(
                    user.stripe_customer_id,
                    amount=applied,
                    currency="gbp",
                    description="Referral credit redeemed on one-time purchase",
                )
            except stripe.error.StripeError as e:
                logger.error("[referral] balance resync failed for %s: %s", user.email, e)

    if user.account_level != AccountLevel.unlimited:
        user.account_level = AccountLevel.paid
    db.commit()
    logger.info("[webhook] granted sessions — user=%s sessions_remaining=%d", user.email, user.sessions_remaining)


def _handle_invoice_paid(inv: dict, db: Session):
    """Mark first invoice paid and deduct any referral credit consumed."""
    customer_id = inv.get("customer")
    if not customer_id:
        return
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        return
    if not user.sub_invoice_paid and (inv.get("amount_paid") or 0) > 0:
        user.sub_invoice_paid = True
    starting = inv.get("starting_balance", 0) or 0
    ending = inv.get("ending_balance", 0) or 0
    consumed = ending - starting
    if consumed > 0:
        user.referral_credit_pence = max(0, user.referral_credit_pence - consumed)
        logger.info("[referral] invoice paid — deducted %dp credit for %s", consumed, user.email)
    db.commit()
