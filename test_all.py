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


print(f"\n{BOLD}-- Interview sessions ------------------------------{RESET}")

def _make_test_user(db):
    from models import AccountLevel, User
    from auth import hash_password
    import secrets
    tag = secrets.token_hex(4)
    u = User(
        username=f"_sess_test_{tag}",
        email=f"_sess_{tag}@test.internal",
        full_name="Session Test",
        password_hash=hash_password("testpass"),
        account_level=AccountLevel.trial,
        api_token=secrets.token_urlsafe(32),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u

def test_session_created_on_first_capture():
    from database import SessionLocal, init_db
    from models import InterviewSession
    from server import _get_or_create_session
    init_db()
    db = SessionLocal()
    try:
        u = _make_test_user(db)
        session = _get_or_create_session(db, u.id)
        assert session.id is not None
        assert session.user_id == u.id
        assert session.ended_at is None
        from datetime import datetime, timedelta
        assert session.expires_at > datetime.utcnow()
        assert session.expires_at < datetime.utcnow() + timedelta(hours=3)
    finally:
        db.query(InterviewSession).filter(InterviewSession.user_id == u.id).delete()
        db.delete(u)
        db.commit()
        db.close()

def test_session_reused_within_window():
    from database import SessionLocal, init_db
    from models import InterviewSession
    from server import _get_or_create_session
    init_db()
    db = SessionLocal()
    try:
        u = _make_test_user(db)
        s1 = _get_or_create_session(db, u.id)
        s2 = _get_or_create_session(db, u.id)
        assert s1.id == s2.id, "should reuse the active session"
    finally:
        db.query(InterviewSession).filter(InterviewSession.user_id == u.id).delete()
        db.delete(u)
        db.commit()
        db.close()

def test_new_session_created_after_expiry():
    from database import SessionLocal, init_db
    from models import InterviewSession
    from server import _get_or_create_session
    from datetime import datetime, timedelta
    init_db()
    db = SessionLocal()
    try:
        u = _make_test_user(db)
        s1 = _get_or_create_session(db, u.id)
        # force expiry
        s1.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        s2 = _get_or_create_session(db, u.id)
        assert s2.id != s1.id, "should create a new session after expiry"
    finally:
        db.query(InterviewSession).filter(InterviewSession.user_id == u.id).delete()
        db.delete(u)
        db.commit()
        db.close()

def test_session_duration_is_2h30m():
    from database import SessionLocal, init_db
    from models import InterviewSession
    from server import _get_or_create_session, SESSION_DURATION
    from datetime import timedelta
    assert SESSION_DURATION == timedelta(hours=2, minutes=30)
    init_db()
    db = SessionLocal()
    try:
        u = _make_test_user(db)
        s = _get_or_create_session(db, u.id)
        delta = s.expires_at - s.started_at
        assert delta == SESSION_DURATION
    finally:
        db.query(InterviewSession).filter(InterviewSession.user_id == u.id).delete()
        db.delete(u)
        db.commit()
        db.close()

test("Session created on first hotkey press", test_session_created_on_first_capture)
test("Active session reused within 2.5hr window", test_session_reused_within_window)
test("New session created after expiry", test_new_session_created_after_expiry)
test("Session duration is exactly 2h30m", test_session_duration_is_2h30m)


print(f"\n{BOLD}-- Server imports ----------------------------------{RESET}")

def test_server_imports():
    import server  # noqa
    import billing  # noqa
    import auth     # noqa
    import models   # noqa

test("All server modules import cleanly", test_server_imports)


# -- HTTP routes (TestClient) -------------------------------------------------

print(f"\n{BOLD}-- HTTP routes (TestClient) ------------------------{RESET}")

from fastapi.testclient import TestClient
from server import app as _fastapi_app


def _make_cookie(account_level):
    from database import SessionLocal
    from models import User
    from auth import hash_password, create_token
    import secrets as _sec
    tag = _sec.token_hex(4)
    uname = f"_http_{account_level.value}_{tag}"
    db = SessionLocal()
    try:
        u = User(
            username=uname, email=f"{uname}@test.internal",
            full_name="HTTP Test", password_hash=hash_password("testpass"),
            account_level=account_level,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return create_token(u.id), uname
    finally:
        db.close()


def _delete_user(username):
    from database import SessionLocal
    from models import User
    db = SessionLocal()
    db.query(User).filter(User.username == username).delete()
    db.commit()
    db.close()


with TestClient(_fastapi_app) as _client:

    def test_http_landing_page():
        r = _client.get("/")
        assert r.status_code == 200

    def test_http_app_redirects_to_login_when_unauthenticated():
        r = _client.get("/app", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "login" in r.headers.get("location", "")

    def test_http_login_rejects_wrong_credentials():
        r = _client.post("/auth/login", json={"username": "nobody", "password": "wrongpass"})
        assert r.status_code == 401

    def test_http_login_rejects_missing_fields():
        r = _client.post("/auth/login", json={"username": "missing_password"})
        assert r.status_code == 422

    def test_http_register_rejects_short_password():
        r = _client.post("/auth/register", json={
            "full_name": "Test", "username": "_reg_pw_test", "email": "_reg_pw@test.internal",
            "password": "short",
        })
        assert r.status_code == 400

    def test_http_register_rejects_duplicate_username():
        from database import SessionLocal
        from models import AccountLevel, User
        from auth import hash_password
        import secrets as _sec
        tag = _sec.token_hex(4)
        uname = f"_dup_http_{tag}"
        db = SessionLocal()
        try:
            db.add(User(
                username=uname, email=f"{uname}@test.internal",
                full_name="Dup", password_hash=hash_password("testpassword123"),
                account_level=AccountLevel.trial,
            ))
            db.commit()
            r = _client.post("/auth/register", json={
                "full_name": "Dup2", "username": uname,
                "email": f"other_{uname}@test.internal", "password": "testpassword123",
            })
            assert r.status_code == 400
            assert "already taken" in r.json()["detail"].lower()
        finally:
            db.query(User).filter(User.username == uname).delete()
            db.commit()
            db.close()

    def test_http_capture_no_auth_header():
        # HTTPBearer returns 401 or 403 depending on starlette version
        r = _client.post("/api/capture", json={"image": "abc", "complexity": 2, "monitor": "browser"})
        assert r.status_code in (401, 403)

    def test_http_capture_invalid_token():
        r = _client.post(
            "/api/capture",
            json={"image": "abc", "complexity": 2, "monitor": "browser"},
            headers={"Authorization": "Bearer notarealtoken"},
        )
        assert r.status_code == 401

    def test_http_api_me_invalid_token():
        r = _client.get("/api/me", headers={"Authorization": "Bearer notarealtoken"})
        assert r.status_code == 401

    def test_http_stream_unauthenticated():
        r = _client.get("/stream")
        assert r.status_code == 401

    def test_http_latest_unauthenticated():
        r = _client.get("/latest")
        assert r.status_code == 401

    def test_http_free_user_blocked_from_gated_routes():
        from models import AccountLevel
        token, uname = _make_cookie(AccountLevel.free)
        try:
            assert _client.get("/latest", cookies={"session": token}).status_code == 403
            assert _client.get("/stream", cookies={"session": token}).status_code == 403
        finally:
            _delete_user(uname)

    def test_http_trial_user_can_access_latest():
        from models import AccountLevel
        token, uname = _make_cookie(AccountLevel.trial)
        try:
            r = _client.get("/latest", cookies={"session": token})
            assert r.status_code == 200
            body = r.json()
            assert "capture" in body and "settings" in body
        finally:
            _delete_user(uname)

    def test_http_complexity_direction_handles_unknown():
        from models import AccountLevel
        token, uname = _make_cookie(AccountLevel.trial)
        try:
            r = _client.post("/settings/complexity/sideways", cookies={"session": token})
            assert r.status_code == 200
        finally:
            _delete_user(uname)

    test("Landing page returns 200",                        test_http_landing_page)
    test("Unauthenticated /app redirects to login",         test_http_app_redirects_to_login_when_unauthenticated)
    test("Login rejects wrong credentials",                  test_http_login_rejects_wrong_credentials)
    test("Login rejects missing fields (422)",               test_http_login_rejects_missing_fields)
    test("Register rejects short password",                  test_http_register_rejects_short_password)
    test("Register rejects duplicate username",              test_http_register_rejects_duplicate_username)
    test("/api/capture requires auth header",                test_http_capture_no_auth_header)
    test("/api/capture rejects invalid token",               test_http_capture_invalid_token)
    test("/api/me rejects invalid token",                    test_http_api_me_invalid_token)
    test("/stream requires authentication",                  test_http_stream_unauthenticated)
    test("/latest requires authentication",                  test_http_latest_unauthenticated)
    test("Free user blocked from subscription routes",       test_http_free_user_blocked_from_gated_routes)
    test("Trial user can access /latest",                    test_http_trial_user_can_access_latest)
    test("Complexity endpoint handles unknown direction",     test_http_complexity_direction_handles_unknown)


# -- Summary ------------------------------------------------------------------
passed  = sum(1 for _, r, _ in results if r is True)
failed  = sum(1 for _, r, _ in results if r is False)
skipped = sum(1 for _, r, _ in results if r is None)

print(f"\n{BOLD}----------------------------------------------------{RESET}")
print(f"  {PASS} {passed}   {FAIL} {failed}   {SKIP} {skipped}")
print()

sys.exit(1 if failed else 0)
