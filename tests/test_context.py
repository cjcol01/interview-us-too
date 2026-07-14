def register(test, skip, client):
    from auth import create_token
    from database import SessionLocal
    from models import AccountLevel
    from server import CUSTOM_CONTEXT_MAX_LENGTH, _custom_context_suffix
    from tests.helpers import cleanup, make_user

    # -- Helper behaviour ------------------------------------------------

    def test_custom_context_suffix_empty_when_unset():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            assert _custom_context_suffix(u) == ""
        finally:
            cleanup(db, u); db.close()

    def test_custom_context_suffix_includes_text():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            u.custom_context = "Interviewing at Acme Corp for a backend role."
            db.commit()
            suffix = _custom_context_suffix(u)
            assert "Acme Corp" in suffix
        finally:
            cleanup(db, u); db.close()

    # -- POST /api/settings/context (cookie, web-facing) ------------------

    def test_api_settings_context_cookie_persists():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"text": "  Applying to Globex as a data engineer.  "},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.custom_context == "Applying to Globex as a data engineer."
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_blank_clears_value():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            u.custom_context = "Old context"
            db.commit()
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"text": "   "},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.custom_context is None
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_requires_session():
        r = client.post("/api/settings/context", json={"text": "hello"})
        assert r.status_code in (401, 403)

    def test_api_settings_context_rejects_over_max_length():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"text": "x" * (CUSTOM_CONTEXT_MAX_LENGTH + 1)},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    # -- GET /settings reflects saved context ------------------------------

    def test_settings_page_renders_saved_context():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            u.custom_context = "Context for the settings page test."
            db.commit()
            token = create_token(u.id)
            r = client.get("/settings", cookies={"session": token})
            assert r.status_code == 200
            assert "Context for the settings page test." in r.text
        finally:
            cleanup(db, u); db.close()

    test("_custom_context_suffix is empty when unset",              test_custom_context_suffix_empty_when_unset)
    test("_custom_context_suffix includes saved text",              test_custom_context_suffix_includes_text)
    test("POST /api/settings/context (cookie) persists",            test_api_settings_context_cookie_persists)
    test("POST /api/settings/context: blank text clears value",     test_api_settings_context_blank_clears_value)
    test("POST /api/settings/context requires session",             test_api_settings_context_requires_session)
    test("POST /api/settings/context: over max length → 422",       test_api_settings_context_rejects_over_max_length)
    test("GET /settings renders saved custom context",              test_settings_page_renders_saved_context)
