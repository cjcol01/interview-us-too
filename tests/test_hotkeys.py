def register(test, skip, client):
    from database import SessionLocal
    from models import AccountLevel
    from server import HOTKEY_DEFAULTS, _user_hotkeys
    from tests.helpers import cleanup, make_user

    # Hotkeys are now managed via manifest commands / chrome://extensions/shortcuts.
    # The server no longer persists or serves per-user hotkey values.

    def test_api_me_has_no_hotkeys_key():
        """Hotkeys were removed from /api/me — extension uses manifest commands."""
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
            assert "hotkeys" not in r.json()
        finally:
            cleanup(db, u)
            db.close()

    def test_api_me_requires_bearer_token():
        r = client.get("/api/me")
        assert r.status_code in (401, 403)

    def test_api_me_rejects_garbage_token():
        r = client.get("/api/me", headers={"Authorization": "Bearer notavalidtoken"})
        assert r.status_code == 401

    def test_settings_hotkeys_endpoint_gone():
        """POST /api/settings/hotkeys was removed; should return 404 or 405."""
        r = client.post("/api/settings/hotkeys", json=HOTKEY_DEFAULTS)
        assert r.status_code in (404, 405)

    def test_user_hotkeys_helper_always_returns_defaults():
        """_user_hotkeys ignores user properties and always returns HOTKEY_DEFAULTS."""
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            # Even if user has custom values stored, helper now returns defaults
            u.hotkey_capture = "Ctrl+X"
            u.hotkey_toggle  = "Ctrl+Z"
            hk = _user_hotkeys(u)
            assert hk == HOTKEY_DEFAULTS
        finally:
            cleanup(db, u)
            db.close()

    def test_user_hotkeys_helper_no_args():
        """_user_hotkeys can be called with no args and returns HOTKEY_DEFAULTS."""
        hk = _user_hotkeys()
        assert hk == HOTKEY_DEFAULTS

    test("/api/me does not include hotkeys key",                test_api_me_has_no_hotkeys_key)
    test("/api/me requires bearer token",                       test_api_me_requires_bearer_token)
    test("/api/me rejects garbage bearer token",                test_api_me_rejects_garbage_token)
    test("POST /api/settings/hotkeys endpoint is gone",         test_settings_hotkeys_endpoint_gone)
    test("_user_hotkeys always returns defaults",               test_user_hotkeys_helper_always_returns_defaults)
    test("_user_hotkeys works with no args",                    test_user_hotkeys_helper_no_args)
