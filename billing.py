import stripe
from sqlalchemy.orm import Session

from config import BASE_URL, STRIPE_PRICE_ID, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
from models import AccountLevel, User

stripe.api_key = STRIPE_SECRET_KEY


def get_or_create_customer(user: User, db: Session) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(email=user.email, name=user.full_name)
    user.stripe_customer_id = customer.id
    db.commit()
    return customer.id


def create_checkout_session(user: User, db: Session) -> str:
    customer_id = get_or_create_customer(user, db)
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        mode="subscription",
        success_url=f"{BASE_URL}/billing/success",
        cancel_url=f"{BASE_URL}/settings",
    )
    return session.url


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


def _sync_subscription(sub: dict, db: Session):
    user = db.query(User).filter(User.stripe_customer_id == sub["customer"]).first()
    if not user:
        return
    user.stripe_sub_id = sub["id"]
    if sub["status"] in ("active", "trialing"):
        user.account_level = AccountLevel.paid
    elif sub["status"] in ("canceled", "unpaid", "incomplete_expired"):
        user.account_level = AccountLevel.free
    db.commit()
