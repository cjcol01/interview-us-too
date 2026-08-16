import stripe
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from analytics import logger, track
from config import BASE_URL, INTRO_SESSIONS, PACK_SESSIONS, PARTNER_HOLD_DAYS, PARTNER_TIER1_FLAT_PENCE, PARTNER_TIER2_BPS, PARTNER_TIER2_MIN_PAID, PARTNER_TIER3_BPS, STRIPE_INTRO_FREE_COUPON_ID, STRIPE_PRICE_ID, STRIPE_REFERRAL_COUPON_ID, STRIPE_RETENTION_COUPON_ID, STRIPE_SECRET_KEY, STRIPE_SESSIONS_PACK_PRICE_ID, STRIPE_SESSIONS_PRICE_ID, STRIPE_SUB_PRICE_ID, STRIPE_WEBHOOK_SECRET
from models import AccountLevel, CommissionStatus, IntroCardFingerprint, PartnerCommission, Referral, ReferralStatus, User

stripe.api_key = STRIPE_SECRET_KEY

# Paying customers who let their subscription lapse get a second free trial after this
# many days — long enough that it feels like a genuine win-back offer, not a reset exploit.
_TRIAL_REELIGIBILITY_DAYS = 90


def trial_eligible(user: User) -> bool:
    """True if this user should receive a free trial period at checkout.

    New users (never trialled) always qualify. Lapsed paying customers qualify
    again after _TRIAL_REELIGIBILITY_DAYS days — sub_invoice_paid confirms they
    actually paid at least one invoice, so pure trial-and-cancel abusers don't benefit."""
    if not user.sub_trial_used:
        return True
    return (
        user.sub_invoice_paid
        and user.sub_lapsed_at is not None
        and datetime.utcnow() - user.sub_lapsed_at >= timedelta(days=_TRIAL_REELIGIBILITY_DAYS)
    )


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


def _partner_rate_bps(partner: User) -> int:
    """Recurring commission rate. Tiers 2/3 earn a %; Tier 1 (the implicit default, tier < 2)
    earns a flat one-off reward instead, so its % rate is zero."""
    if partner.partner_tier >= 3:
        return PARTNER_TIER3_BPS
    if partner.partner_tier >= 2:
        return PARTNER_TIER2_BPS
    return 0


def _recompute_partner_tier(partner: User, db: Session) -> None:
    """Auto-upgrade a Tier-1 referrer to Tier 2 once enough referees have fully paid. Never
    downgrades, and never touches a tier an admin set manually."""
    if partner.partner_tier_manual:
        return
    # The session is autoflush=False (database.py) — the caller's just-set
    # Referral.status=subscribed wouldn't be visible to this count without a flush.
    db.flush()
    paid_count = db.query(Referral).filter(
        Referral.referrer_id == partner.id,
        Referral.status == ReferralStatus.subscribed,
    ).count()
    if paid_count >= PARTNER_TIER2_MIN_PAID and partner.partner_tier < 2:
        partner.partner_status = "active"
        partner.partner_tier = 2


def _accrue_commission(referrer: User, referee: User, amount_pence: int, kind: str, stripe_ref: str | None, db: Session) -> None:
    """Record a partner's commission on a payment made by one of their referees. Idempotent on stripe_ref —
    caller commits."""
    if amount_pence <= 0 or referrer.partner_status != "active":
        return
    if stripe_ref and db.query(PartnerCommission).filter(PartnerCommission.stripe_ref == stripe_ref).first():
        return  # already recorded — webhook retry
    rate_bps = _partner_rate_bps(referrer)
    commission = amount_pence * rate_bps // 10000
    if commission <= 0:
        return
    is_first_for_referee = db.query(PartnerCommission).filter(
        PartnerCommission.partner_id == referrer.id,
        PartnerCommission.referee_id == referee.id,
    ).first() is None
    now = datetime.utcnow()
    # Only the first commission earned on a given referee is held (refund/chargeback window);
    # every later payment from that same referee matures immediately.
    mature_at = now + timedelta(days=PARTNER_HOLD_DAYS) if is_first_for_referee else now
    status = CommissionStatus.pending if is_first_for_referee else CommissionStatus.available
    db.add(PartnerCommission(
        partner_id=referrer.id,
        referee_id=referee.id,
        source_amount_pence=amount_pence,
        rate_bps=rate_bps,
        amount_pence=commission,
        kind=kind,
        stripe_ref=stripe_ref,
        status=status,
        created_at=now,
        mature_at=mature_at,
    ))
    logger.info("[partner] accrued %dp commission (%d bps) for %s from %s (%s)", commission, rate_bps, referrer.email, referee.email, kind)


def _reward_referrer_on_paid(referrer: User, referee: User, amount_pence: int, kind: str, stripe_ref: str | None, db: Session, accrue_pct: bool = True) -> None:
    """A referee just made a real paid conversion. Tiers 2/3 earn recurring % cash commission;
    Tier 1 (everyone else) earns a one-off account credit toward their own subscription instead —
    no cash, no withdrawal. `accrue_pct=False` for subscriptions, whose % is accrued per-invoice in
    _handle_invoice_paid rather than at activation. Caller commits. Idempotent: callers only reach
    this once per referee, gated on Referral.sub_credited at the call site."""
    if referrer.partner_tier >= 2 and referrer.partner_status == "active":
        if accrue_pct:
            _accrue_commission(referrer, referee, amount_pence, kind, stripe_ref, db)
    elif PARTNER_TIER1_FLAT_PENCE > 0:
        _credit_referrer(referrer, PARTNER_TIER1_FLAT_PENCE, f"Referral reward: {referee.email}")


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
        # A referred user's intro is free. Priority: (1) dedicated 100%-off intro coupon if
        # configured — explicit and card-required; (2) referral coupon (£5) which exceeds the
        # £2 price so Stripe floors it to £0, also card-required; (3) referral account credit.
        if user.referred_by_id and not user.intro_redeemed and STRIPE_INTRO_FREE_COUPON_ID:
            key = "promotion_code" if STRIPE_INTRO_FREE_COUPON_ID.startswith("promo_") else "coupon"
            kwargs["discounts"] = [{key: STRIPE_INTRO_FREE_COUPON_ID}]
        elif apply_referral_discount and STRIPE_REFERRAL_COUPON_ID and not user.intro_redeemed:
            # £5 off a £2 purchase → Stripe clamps to £0. Card is still required (mode=payment).
            key = "promotion_code" if STRIPE_REFERRAL_COUPON_ID.startswith("promo_") else "coupon"
            kwargs["discounts"] = [{key: STRIPE_REFERRAL_COUPON_ID}]
        elif user.referral_credit_pence > 0:
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
        # £5 off the referee's first real paid plan (the pack counts, the £2 intro does not).
        if apply_referral_discount and STRIPE_REFERRAL_COUPON_ID:
            key = "promotion_code" if STRIPE_REFERRAL_COUPON_ID.startswith("promo_") else "coupon"
            kwargs["discounts"] = [{key: STRIPE_REFERRAL_COUPON_ID}]
        elif user.referral_credit_pence > 0:
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
        if trial_eligible(user):
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
    sub = stripe.Subscription.retrieve(user.stripe_sub_id).to_dict()
    period_end = sub.get("cancel_at") or sub.get("trial_end")
    return datetime.utcfromtimestamp(period_end) if period_end else None


def cancel_subscription_immediately(user: User) -> None:
    """Used for account deletion — ends the subscription now rather than at period end."""
    if not user.stripe_sub_id:
        return
    try:
        stripe.Subscription.delete(user.stripe_sub_id)
    except stripe.error.InvalidRequestError:
        pass  # already cancelled / no longer exists


def pause_subscription(user: User) -> None:
    """Admin action — stop Stripe from billing this subscriber without cancelling the
    subscription outright (reversible from the Stripe dashboard). Caller is responsible for
    downgrading the local account_level, since a paused sub still reports status=active."""
    if not user.stripe_sub_id:
        raise ValueError("No active subscription found.")
    stripe.Subscription.modify(user.stripe_sub_id, pause_collection={"behavior": "void"})


def resume_subscription(user: User, db: Session) -> None:
    """Admin action — reverses pause_subscription. Resumes Stripe billing and resyncs
    account_level from Stripe's actual subscription state (same path the webhook uses),
    rather than assuming it's still active."""
    if not user.stripe_sub_id:
        raise ValueError("No active subscription found.")
    stripe.Subscription.modify(user.stripe_sub_id, pause_collection="")
    sub = stripe.Subscription.retrieve(user.stripe_sub_id).to_dict()
    _sync_subscription(sub, db)


def create_portal_session(user: User) -> str:
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{BASE_URL}/settings",
    )
    return session.url


def handle_webhook_event(payload: bytes, sig_header: str, db: Session):
    event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    data = event["data"]["object"].to_dict()

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
    # pause_collection doesn't change status — a paused sub still reports active/trialing.
    # Treat it as free while paused, and skip the "just activated" side effects (referral
    # credit, trial flag, tracking) below, since a pause isn't a genuine activation event.
    if sub.get("pause_collection"):
        user.account_level = AccountLevel.free
    elif sub["status"] in ("active", "trialing"):
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
                    # Tier 1 earns a flat one-off reward on this first paid conversion; Tiers 2/3
                    # earn recurring % instead — accrued per invoice in _handle_invoice_paid.
                    _reward_referrer_on_paid(referrer, user, 0, "subscription", sub["id"], db, accrue_pct=False)
                    ref.sub_credited = True
                    ref.status = ReferralStatus.subscribed
                    ref.sub_at = datetime.utcnow()
                    _recompute_partner_tier(referrer, db)
        track(user.id, "subscription_created", via_referral=bool(user.referred_by_id))
    elif sub["status"] in ("canceled", "unpaid", "incomplete_expired"):
        user.account_level = AccountLevel.free
        user.sub_cancel_at = None
        user.sub_lapsed_at = datetime.utcnow()
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
        user.sessions_remaining += INTRO_SESSIONS
        user.intro_redeemed = True
        if user.referred_by_id:
            ref = db.query(Referral).filter(
                Referral.referee_id == user.id,
                Referral.intro_credited == False,  # noqa: E712
            ).first()
            if ref:
                # No referrer reward on the intro — the flat/% payout fires only on a real paid
                # plan (£10 pack or £15 sub). We still record that the intro was used.
                ref.intro_credited = True
                ref.status = ReferralStatus.intro
                ref.intro_at = datetime.utcnow()
        track(user.id, "sessions_purchased", plan="sessions", sessions_added=INTRO_SESSIONS)

    elif plan == "sessions_pack":
        user.sessions_remaining += PACK_SESSIONS
        if user.referred_by_id:
            ref = db.query(Referral).filter(
                Referral.referee_id == user.id,
                Referral.sub_credited == False,  # noqa: E712
            ).first()
            if ref:
                referrer = db.query(User).filter(User.id == ref.referrer_id).first()
                if referrer:
                    _reward_referrer_on_paid(referrer, user, data.get("amount_total") or 0, "sessions_pack", data.get("id"), db)
                    ref.sub_credited = True
                    ref.status = ReferralStatus.subscribed
                    ref.sub_at = datetime.utcnow()
                    _recompute_partner_tier(referrer, db)
        track(user.id, "sessions_purchased", plan="sessions_pack", sessions_added=PACK_SESSIONS)

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
    # Subscription commission (first payment and every renewal) accrues here, off the real
    # amount Stripe collected — not in _sync_subscription, which only sees status transitions.
    if user.referred_by_id:
        referrer = db.query(User).filter(User.id == user.referred_by_id).first()
        if referrer:
            _accrue_commission(referrer, user, inv.get("amount_paid") or 0, "subscription", inv.get("id"), db)
    db.commit()
