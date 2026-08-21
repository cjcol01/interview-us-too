def register(test, skip, client):
    from auth import create_token
    from config import ANTHROPIC_API_KEY
    from database import SessionLocal
    from models import AccountLevel
    from server import HOTKEY_DEFAULTS, _user_hotkeys
    from tests.helpers import cleanup, make_user

    live_ok = ANTHROPIC_API_KEY and not ANTHROPIC_API_KEY.startswith("sk-ant-...")

    # ── Typing hotkey defaults ───────────────────────────────────────────────

    def test_typing_hotkey_default():
        # Hotkeys are now static defaults (manifest commands); /api/me no longer returns them.
        # Test that _user_hotkeys always returns the correct default regardless of user state.
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            assert _user_hotkeys(u)["typing"] == HOTKEY_DEFAULTS["typing"]
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
            assert "hotkeys" not in r.json()
        finally:
            cleanup(db, u)
            db.close()

    # ── Passthrough setting ──────────────────────────────────────────────────

    def test_passthrough_default_true():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            assert u.typing_passthrough is True
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.json()["typing_passthrough"] is True
        finally:
            cleanup(db, u)
            db.close()

    def test_passthrough_persists_false():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post("/api/settings/passthrough", json={"enabled": False}, cookies={"session": token})
            assert r.status_code == 200
            db.refresh(u)
            assert u.typing_passthrough is False
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.json()["typing_passthrough"] is False
        finally:
            cleanup(db, u)
            db.close()

    def test_passthrough_requires_cookie_auth():
        r = client.post("/api/settings/passthrough", json={"enabled": True})
        assert r.status_code == 401

    def test_passthrough_missing_field_is_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post("/api/settings/passthrough", json={}, cookies={"session": token})
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    # ── /api/text-capture gating & validation ────────────────────────────────

    def test_text_capture_free_user_blocked():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.free)
            r = client.post("/api/text-capture", json={"text": "hi"},
                            headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 403
        finally:
            cleanup(db, u)
            db.close()

    def test_text_capture_trial_without_session_blocked():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.post("/api/text-capture", json={"text": "hi"},
                            headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 403
            assert "trial_expired" in r.json().get("detail", "")
        finally:
            cleanup(db, u)
            db.close()

    def test_text_capture_invalid_token_is_401():
        r = client.post("/api/text-capture", json={"text": "hi"},
                        headers={"Authorization": "Bearer notavalidtoken"})
        assert r.status_code == 401

    def test_text_capture_missing_text_is_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            r = client.post("/api/text-capture", json={},
                            headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    def test_text_capture_empty_text_is_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            r = client.post("/api/text-capture", json={"text": ""},
                            headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    def test_text_capture_too_long_is_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            r = client.post("/api/text-capture", json={"text": "x" * 5001},
                            headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    def test_text_capture_paid_exhausted_is_403():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            u.sessions_remaining = 0
            db.commit()
            r = client.post("/api/text-capture", json={"text": "hi"},
                            headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 403
            assert "sessions_exhausted" in r.json().get("detail", "")
        finally:
            cleanup(db, u)
            db.close()

    def test_text_capture_paid_happy_path_live():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            u.sessions_remaining = 5
            db.commit()
            r = client.post("/api/text-capture",
                            json={"text": "What is the time complexity of binary search?"},
                            headers={"Authorization": f"Bearer {u.api_token}"}, timeout=60)
            assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
            assert r.json() == {"status": "ok"}
        finally:
            cleanup(db, u)
            db.close()

    test("Typing hotkey default in /api/me + helper",          test_typing_hotkey_default)
    test("typing_passthrough defaults to True",                test_passthrough_default_true)
    test("POST /api/settings/passthrough persists (False)",    test_passthrough_persists_false)
    test("/api/settings/passthrough requires cookie auth",     test_passthrough_requires_cookie_auth)
    test("/api/settings/passthrough: missing field → 422",     test_passthrough_missing_field_is_422)
    test("Free user blocked from /api/text-capture (403)",     test_text_capture_free_user_blocked)
    test("Trial without session blocked (trial_expired)",      test_text_capture_trial_without_session_blocked)
    test("/api/text-capture invalid token → 401",              test_text_capture_invalid_token_is_401)
    test("/api/text-capture missing text → 422",               test_text_capture_missing_text_is_422)
    test("/api/text-capture empty text → 422",                 test_text_capture_empty_text_is_422)
    test("/api/text-capture text >5000 chars → 422",           test_text_capture_too_long_is_422)
    test("/api/text-capture paid w/ no sessions → 403",        test_text_capture_paid_exhausted_is_403)

    if live_ok:
        test("Paid user text capture end-to-end (live API)",   test_text_capture_paid_happy_path_live)
    else:
        skip("Paid user text capture end-to-end (live API)",   "ANTHROPIC_API_KEY not configured")
