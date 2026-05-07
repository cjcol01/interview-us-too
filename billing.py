import stripe
from datetime import datetime
from sqlalchemy.orm import Session

from config import BASE_URL, STRIPE_PRICE_ID, STRIPE_SECRET_KEY, STRIPE_SESSIONS_PACK_PRICE_ID, STRIPE_SESSIONS_PRICE_ID, STRIPE_SUB_PRICE_ID, STRIPE_WEBHOOK_SECRET
from models import AccountLevel, IntroCardFingerprint, User

stripe.api_key = STRIPE_SECRET_KEY


def get_or_create_customer(user: User, db: Session) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(email=user.email, name=user.full_name)
    user.stripe_customer_id = customer.id
    db.commit()
    return customer.id


def create_checkout_session(user: User, db: Session, plan: str = "subscription") -> str:
    customer_id = get_or_create_customer(user, db)

    if plan == "sessions":
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_SESSIONS_PRICE_ID, "quantity": 1}],
            mode="payment",
            metadata={"plan": "sessions"},
            success_url=f"{BASE_URL}/billing/success",
            cancel_url=f"{BASE_URL}/pricing",
        )
    elif plan == "sessions_pack":
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_SESSIONS_PACK_PRICE_ID, "quantity": 1}],
            mode="payment",
            metadata={"plan": "sessions_pack"},
            success_url=f"{BASE_URL}/billing/success",
            cancel_url=f"{BASE_URL}/pricing",
        )
    else:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_SUB_PRICE_ID or STRIPE_PRICE_ID, "quantity": 1}],
            mode="subscription",
            subscription_data={"trial_period_days": 7},
            success_url=f"{BASE_URL}/billing/success",
            cancel_url=f"{BASE_URL}/pricing",
        )

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


def _sync_subscription(sub: dict, db: Session):
    user = db.query(User).filter(User.stripe_customer_id == sub["customer"]).first()
    if not user:
        return
    user.stripe_sub_id = sub["id"]
    if sub["status"] in ("active", "trialing"):
        user.account_level = AccountLevel.unlimited
        period_end = sub.get("cancel_at") or sub.get("trial_end")
        if sub.get("cancel_at_period_end") and period_end:
            user.sub_cancel_at = datetime.utcfromtimestamp(period_end)
        elif not sub.get("cancel_at_period_end"):
            user.sub_cancel_at = None
    elif sub["status"] in ("canceled", "unpaid", "incomplete_expired"):
        user.account_level = AccountLevel.free
        user.sub_cancel_at = None
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
    print(f"[webhook] sessions purchase: customer={customer_id} mode={data.get('mode')} metadata={data.get('metadata')}")
    user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
    if not user:
        print(f"[webhook] no user found for customer {customer_id}")
        return
    plan = (data.get("metadata") or {}).get("plan", "")
    print(f"[webhook] user={user.email} plan={plan!r} sessions_remaining={user.sessions_remaining}")
    if plan == "sessions":
        if not STRIPE_SECRET_KEY.startswith("sk_test_"):
            fingerprint = _get_card_fingerprint(data)
            if fingerprint:
                already_used = db.query(IntroCardFingerprint).filter(
                    IntroCardFingerprint.fingerprint == fingerprint
                ).first()
                if already_used:
                    print(f"[webhook] fingerprint already used — refunding")
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
        user.sessions_remaining += 2
        user.intro_redeemed = True
    elif plan == "sessions_pack":
        user.sessions_remaining += 3
    else:
        print(f"[webhook] unrecognised plan {plan!r} — ignoring")
        return

    user.account_level = AccountLevel.paid
    db.commit()
    print(f"[webhook] granted sessions — user={user.email} sessions_remaining={user.sessions_remaining} account_level={user.account_level}")
