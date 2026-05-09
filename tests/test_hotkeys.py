def register(test, skip, client):
    from auth import create_token
    from database import SessionLocal
    from models import AccountLevel
    from server import HOTKEY_DEFAULTS, _user_hotkeys
    from tests.helpers import cleanup, make_user

    def test_defaults_via_api_me():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
            body = r.json()
            assert body["hotkeys"] == HOTKEY_DEFAULTS
        finally:
            cleanup(db, u)
            db.close()

    def test_hotkeys_persist():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            payload = {"capture": "Ctrl+1", "audio": "Ctrl+2", "toggle": "Ctrl+3"}
            r = client.post(
                "/api/settings/hotkeys",
                json=payload,
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.hotkey_capture == "Ctrl+1"
            assert u.hotkey_audio   == "Ctrl+2"
            assert u.hotkey_toggle  == "Ctrl+3"
        finally:
            cleanup(db, u)
            db.close()

    def test_saved_hotkeys_returned_by_api_me():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            payload = {"capture": "Alt+A", "audio": "Alt+B", "toggle": "Alt+C"}
            client.post("/api/settings/hotkeys", json=payload, cookies={"session": token})
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
            assert r.json()["hotkeys"] == payload
        finally:
            cleanup(db, u)
            db.close()

    def test_hotkeys_requires_cookie_auth():
        r = client.post("/api/settings/hotkeys", json=HOTKEY_DEFAULTS)
        assert r.status_code == 401

    def test_api_me_requires_bearer_token():
        r = client.get("/api/me")
        assert r.status_code in (401, 403)

    def test_api_me_rejects_garbage_token():
        r = client.get("/api/me", headers={"Authorization": "Bearer notavalidtoken"})
        assert r.status_code == 401

    def test_hotkeys_missing_field_is_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/hotkeys",
                json={"capture": "Ctrl+1", "audio": "Ctrl+2"},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    def test_user_hotkeys_helper_falls_back_to_defaults():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            u.hotkey_capture = None
            u.hotkey_audio   = None
            u.hotkey_toggle  = None
            hk = _user_hotkeys(u)
            assert hk == HOTKEY_DEFAULTS
        finally:
            cleanup(db, u)
            db.close()

    def test_user_hotkeys_helper_uses_custom_values():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            u.hotkey_capture = "Ctrl+X"
            u.hotkey_audio   = "Ctrl+Y"
            u.hotkey_toggle  = "Ctrl+Z"
            hk = _user_hotkeys(u)
            assert hk == {"capture": "Ctrl+X", "audio": "Ctrl+Y", "toggle": "Ctrl+Z"}
        finally:
            cleanup(db, u)
            db.close()

    test("Hotkey defaults returned by /api/me",               test_defaults_via_api_me)
    test("POST /api/settings/hotkeys persists to DB",         test_hotkeys_persist)
    test("Saved hotkeys readable via /api/me",                test_saved_hotkeys_returned_by_api_me)
    test("/api/settings/hotkeys requires cookie auth",        test_hotkeys_requires_cookie_auth)
    test("/api/me requires bearer token",                     test_api_me_requires_bearer_token)
    test("/api/me rejects garbage bearer token",              test_api_me_rejects_garbage_token)
    test("/api/settings/hotkeys: missing field → 422",        test_hotkeys_missing_field_is_422)
    test("_user_hotkeys falls back to defaults for None",     test_user_hotkeys_helper_falls_back_to_defaults)
    test("_user_hotkeys returns custom values",               test_user_hotkeys_helper_uses_custom_values)
