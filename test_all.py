"""
Quick smoke test — run with: python test_all.py
Tests core systems without needing the server running.
"""
import sys
import traceback

PASS = "\033[92m PASS\033[0m"
FAIL = "\033[91m FAIL\033[0m"
SKIP = "\033[93m SKIP\033[0m"
BOLD = "\033[1m"
RESET = "\033[0m"

results = []

def test(name, fn):
    try:
        result = fn()
        if result is False:
            print(f"{FAIL} {name}")
            results.append((name, False, None))
        else:
            print(f"{PASS} {name}")
            results.append((name, True, None))
    except Exception as e:
        print(f"{FAIL} {name}")
        print(f"       {type(e).__name__}: {e}")
        results.append((name, False, e))

def skip(name, reason):
    print(f"{SKIP} {name} ({reason})")
    results.append((name, None, None))

# -- suppress noisy warnings --------------------------------------------------
import warnings
warnings.filterwarnings("ignore")
import logging
logging.disable(logging.CRITICAL)


print(f"\n{BOLD}-- Config ------------------------------------------{RESET}")

def test_config_loads():
    import config
    assert config.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY not set"
    assert config.SECRET_KEY != "change-me-in-production", "SECRET_KEY is still default"

def test_stripe_keys_present():
    import config
    assert config.STRIPE_SECRET_KEY and not config.STRIPE_SECRET_KEY.startswith("sk_test_..."), \
        "STRIPE_SECRET_KEY not configured"

test("Config loads and required keys present", test_config_loads)
test("Stripe keys configured", test_stripe_keys_present)


print(f"\n{BOLD}-- Database ----------------------------------------{RESET}")

def test_db_init():
    from database import init_db
    init_db()

def test_db_create_read_delete():
    from database import SessionLocal, init_db
    from models import AccountLevel, User
    from auth import hash_password
    from datetime import datetime

    init_db()
    db = SessionLocal()
    try:
        u = User(
            username="_smoke_test_user",
            email="_smoke@test.internal",
            full_name="Smoke Test",
            password_hash=hash_password("testpassword123"),
            account_level=AccountLevel.trial,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        assert u.id is not None
        fetched = db.query(User).filter(User.username == "_smoke_test_user").first()
        assert fetched is not None
        assert fetched.full_name == "Smoke Test"
        db.delete(fetched)
        db.commit()
        assert db.query(User).filter(User.username == "_smoke_test_user").first() is None
    finally:
        db.close()

test("Database initialises", test_db_init)
test("Create / read / delete user", test_db_create_read_delete)


print(f"\n{BOLD}-- Auth --------------------------------------------{RESET}")

def test_password_hashing():
    from auth import hash_password, verify_password
    hashed = hash_password("mysecretpassword")
    assert verify_password("mysecretpassword", hashed)
    assert not verify_password("wrongpassword", hashed)

def test_token_roundtrip():
    from auth import create_token
    from jose import jwt
    from config import SECRET_KEY
    token = create_token(user_id=42)
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    assert int(payload["sub"]) == 42

def test_duplicate_user_rejected():
    from database import SessionLocal, init_db
    from models import AccountLevel, User
    from auth import hash_password
    from sqlalchemy.exc import IntegrityError

    init_db()
    db = SessionLocal()
    try:
        for _ in range(2):
            db.add(User(
                username="_dup_test",
                email="_dup@test.internal",
                full_name="Dup",
                password_hash=hash_password("pass"),
                account_level=AccountLevel.trial,
            ))
        db.commit()
        return False  # should have raised
    except IntegrityError:
        db.rollback()
        return True
    finally:
        u = db.query(User).filter(User.username == "_dup_test").first()
        if u:
            db.delete(u)
            db.commit()
        db.close()

test("Password hashing and verification", test_password_hashing)
test("JWT token creation and decode", test_token_roundtrip)
test("Duplicate username rejected", test_duplicate_user_rejected)


print(f"\n{BOLD}-- Screenshot capture ------------------------------{RESET}")

def test_capture():
    import platform
    if platform.system() != "Windows":
        return skip("Screenshot capture", "not on Windows")
    from capture import screenshot
    import mss
    with mss.mss() as sct:
        count = len(sct.monitors) - 1
    data = screenshot(1)
    assert isinstance(data, bytes) and len(data) > 1000, "screenshot data too small"
    print(f"       {count} monitor(s) detected, captured {len(data)//1024}KB")

import platform
if platform.system() == "Windows":
    test("Screenshot capture (monitor 1)", test_capture)
else:
    skip("Screenshot capture", "not on Windows")


print(f"\n{BOLD}-- Claude API --------------------------------------{RESET}")

def test_claude_connection():
    import anthropic
    from config import ANTHROPIC_API_KEY
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16,
        messages=[{"role": "user", "content": "Reply with only: ok"}],
    )
    assert resp.content[0].text.strip().lower().startswith("ok")

test("Claude API connection and response", test_claude_connection)


print(f"\n{BOLD}-- Stripe API --------------------------------------{RESET}")

def test_stripe_connection():
    import stripe
    from config import STRIPE_SECRET_KEY
    if not STRIPE_SECRET_KEY or STRIPE_SECRET_KEY.startswith("sk_test_..."):
        raise AssertionError("Stripe key not configured")
    stripe.api_key = STRIPE_SECRET_KEY
    products = stripe.Product.list(limit=1)
    assert "data" in dict(products)

test("Stripe API connection", test_stripe_connection)


print(f"\n{BOLD}-- Server imports ----------------------------------{RESET}")

def test_server_imports():
    import server  # noqa
    import billing  # noqa
    import auth     # noqa
    import models   # noqa

test("All server modules import cleanly", test_server_imports)


# -- Summary ------------------------------------------------------------------
passed  = sum(1 for _, r, _ in results if r is True)
failed  = sum(1 for _, r, _ in results if r is False)
skipped = sum(1 for _, r, _ in results if r is None)

print(f"\n{BOLD}----------------------------------------------------{RESET}")
print(f"  {PASS} {passed}   {FAIL} {failed}   {SKIP} {skipped}")
print()

sys.exit(1 if failed else 0)
