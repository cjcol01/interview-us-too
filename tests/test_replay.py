def register(test, skip, client):
    from auth import create_token
    from database import SessionLocal
    from models import AccountLevel
    from server import HOTKEY_DEFAULTS, _user_hotkeys
    from tests.helpers import cleanup, make_user

    # ── 1. Defaults on fresh user ────────────────────────────────────────────

    def test_defaults_columns():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            assert u.replay_enabled is False
            assert u.replay_seconds == 10
            assert u.hotkey_replay is None
        finally:
            cleanup(db, u)
            db.close()

    def test_defaults_in_user_hotkeys_helper():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            hk = _user_hotkeys(u)
            assert hk["replay"] == HOTKEY_DEFAULTS["replay"]
        finally:
            cleanup(db, u)
            db.close()

    # ── 2. POST /api/settings/replay persists ────────────────────────────────

    def test_replay_persist_enabled_5s():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/replay",
                json={"enabled": True, "seconds": 5},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.replay_enabled is True
            assert u.replay_seconds == 5
        finally:
            cleanup(db, u)
            db.close()

    def test_replay_persist_enabled_25s():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/replay",
                json={"enabled": True, "seconds": 25},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.replay_enabled is True
            assert u.replay_seconds == 25
        finally:
            cleanup(db, u)
            db.close()

    def test_replay_persist_disabled():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/replay",
                json={"enabled": False, "seconds": 10},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.replay_enabled is False
            assert u.replay_seconds == 10
        finally:
            cleanup(db, u)
            db.close()

    # ── 3. POST /api/settings/replay validation ──────────────────────────────

    def test_replay_rejects_seconds_zero():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/replay",
                json={"enabled": True, "seconds": 0},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    def test_replay_rejects_seconds_31():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/replay",
                json={"enabled": True, "seconds": 31},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    def test_replay_rejects_float_seconds():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/replay",
                json={"enabled": True, "seconds": 5.5},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    def test_replay_rejects_missing_fields():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/replay",
                json={"enabled": True},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    # ── 4. POST /api/settings/hotkeys accepts replay field ───────────────────

    def test_hotkeys_with_replay_field_persists():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/hotkeys",
                json={"capture": "Ctrl+1", "audio": "Ctrl+2", "toggle": "Ctrl+3", "replay": "Ctrl+Alt+R", "typing": "Ctrl+Shift+5"},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.hotkey_replay == "Ctrl+Alt+R"
        finally:
            cleanup(db, u)
            db.close()

    def test_hotkeys_without_replay_is_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/hotkeys",
                json={"capture": "Ctrl+1", "audio": "Ctrl+2", "toggle": "Ctrl+3"},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    # ── 5. /api/me shape includes replay ─────────────────────────────────────

    def test_api_me_includes_replay_defaults():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
            body = r.json()
            assert "replay" in body
            assert body["replay"]["enabled"] is False
            assert body["replay"]["seconds"] == 10
            assert "replay" in body["hotkeys"]
            assert body["hotkeys"]["replay"] == HOTKEY_DEFAULTS["replay"]
        finally:
            cleanup(db, u)
            db.close()

    def test_api_me_reflects_saved_replay():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            client.post(
                "/api/settings/replay",
                json={"enabled": True, "seconds": 15},
                cookies={"session": token},
            )
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
            body = r.json()
            assert body["replay"]["enabled"] is True
            assert body["replay"]["seconds"] == 15
        finally:
            cleanup(db, u)
            db.close()

    # ── 6. Auth gating ───────────────────────────────────────────────────────

    def test_replay_requires_auth():
        r = client.post("/api/settings/replay", json={"enabled": True, "seconds": 10})
        assert r.status_code == 401

    test("Replay defaults on fresh user (columns)",               test_defaults_columns)
    test("Replay default reflected in _user_hotkeys helper",      test_defaults_in_user_hotkeys_helper)
    test("POST /api/settings/replay persists (enabled, 5s)",      test_replay_persist_enabled_5s)
    test("POST /api/settings/replay persists (enabled, 25s)",     test_replay_persist_enabled_25s)
    test("POST /api/settings/replay persists (disabled)",         test_replay_persist_disabled)
    test("POST /api/settings/replay: seconds=0 → 422",           test_replay_rejects_seconds_zero)
    test("POST /api/settings/replay: seconds=31 → 422",          test_replay_rejects_seconds_31)
    test("POST /api/settings/replay: float seconds → 422",        test_replay_rejects_float_seconds)
    test("POST /api/settings/replay: missing fields → 422",       test_replay_rejects_missing_fields)
    test("POST /api/settings/hotkeys: replay field persists",     test_hotkeys_with_replay_field_persists)
    test("POST /api/settings/hotkeys: omitting replay → 422",     test_hotkeys_without_replay_is_422)
    test("/api/me includes replay defaults",                      test_api_me_includes_replay_defaults)
    test("/api/me reflects saved replay settings",                test_api_me_reflects_saved_replay)
    test("POST /api/settings/replay requires session auth",       test_replay_requires_auth)
