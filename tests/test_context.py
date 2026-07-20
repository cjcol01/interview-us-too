def register(test, skip, client):
    from auth import create_token
    from database import SessionLocal
    from models import AccountLevel, InterviewContext
    from server import CONTEXT_TEXT_MAX_LENGTH, MAX_CONTEXTS_PER_USER, _context_suffix
    from tests.helpers import cleanup, make_user

    # -- Helper behaviour ------------------------------------------------

    def test_context_suffix_empty_when_no_active_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            assert _context_suffix(u, db) == ""
        finally:
            cleanup(db, u); db.close()

    def test_context_suffix_includes_active_slot_text():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="Acme", text="Interviewing at Acme Corp for a backend role."))
            u.active_context_slot = 1
            db.commit()
            suffix = _context_suffix(u, db)
            assert "Acme Corp" in suffix
        finally:
            cleanup(db, u); db.close()

    def test_context_suffix_ignores_inactive_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="Acme", text="Interviewing at Acme Corp."))
            db.commit()
            # slot 1 is saved but not marked active
            assert _context_suffix(u, db) == ""
        finally:
            cleanup(db, u); db.close()

    # -- POST /api/settings/context (cookie, web-facing) ------------------

    def test_api_settings_context_persists():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"slot": 1, "name": "Globex", "text": "  Applying to Globex as a data engineer.  "},
                cookies={"session": token},
            )
            assert r.status_code == 200
            ctx = db.query(InterviewContext).filter(InterviewContext.user_id == u.id, InterviewContext.slot == 1).first()
            assert ctx.name == "Globex"
            assert ctx.text == "Applying to Globex as a data engineer."
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_blank_clears_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="Old", text="Old context"))
            u.active_context_slot = 1
            db.commit()
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"slot": 1, "name": "  ", "text": "   "},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert db.query(InterviewContext).filter(InterviewContext.user_id == u.id, InterviewContext.slot == 1).first() is None
            assert u.active_context_slot is None
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_requires_session():
        r = client.post("/api/settings/context", json={"slot": 1, "name": "x", "text": "hello"})
        assert r.status_code in (401, 403)

    def test_api_settings_context_rejects_over_max_length():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"slot": 1, "name": "x", "text": "x" * (CONTEXT_TEXT_MAX_LENGTH + 1)},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_rejects_slot_out_of_range():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/context",
                json={"slot": MAX_CONTEXTS_PER_USER + 1, "name": "x", "text": "hello"},
                cookies={"session": token},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    # -- POST /api/settings/context/activate -------------------------------

    def test_api_settings_context_activate_sets_active_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=2, name="Globex", text="Data engineer role at Globex."))
            db.commit()
            token = create_token(u.id)
            r = client.post("/api/settings/context/activate", json={"slot": 2}, cookies={"session": token})
            assert r.status_code == 200
            db.refresh(u)
            assert u.active_context_slot == 2
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_activate_null_clears_active_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="Acme", text="Acme role."))
            u.active_context_slot = 1
            db.commit()
            token = create_token(u.id)
            r = client.post("/api/settings/context/activate", json={"slot": None}, cookies={"session": token})
            assert r.status_code == 200
            db.refresh(u)
            assert u.active_context_slot is None
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_context_activate_rejects_empty_slot():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post("/api/settings/context/activate", json={"slot": 3}, cookies={"session": token})
            assert r.status_code == 400
        finally:
            cleanup(db, u); db.close()

    # -- GET /settings reflects saved contexts ------------------------------

    def test_settings_page_renders_saved_contexts():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            db.add(InterviewContext(user_id=u.id, slot=1, name="Acme", text="Context for the settings page test."))
            db.commit()
            token = create_token(u.id)
            r = client.get("/settings", cookies={"session": token})
            assert r.status_code == 200
            assert "Context for the settings page test." in r.text
        finally:
            cleanup(db, u); db.close()

    test("_context_suffix is empty when no slot is active",           test_context_suffix_empty_when_no_active_slot)
    test("_context_suffix includes the active slot's text",           test_context_suffix_includes_active_slot_text)
    test("_context_suffix ignores a saved-but-inactive slot",         test_context_suffix_ignores_inactive_slot)
    test("POST /api/settings/context persists name+text",             test_api_settings_context_persists)
    test("POST /api/settings/context: blank clears the slot",         test_api_settings_context_blank_clears_slot)
    test("POST /api/settings/context requires session",               test_api_settings_context_requires_session)
    test("POST /api/settings/context: over max length → 422",         test_api_settings_context_rejects_over_max_length)
    test("POST /api/settings/context: slot out of range → 422",       test_api_settings_context_rejects_slot_out_of_range)
    test("POST /api/settings/context/activate sets active slot",      test_api_settings_context_activate_sets_active_slot)
    test("POST /api/settings/context/activate: null clears active",   test_api_settings_context_activate_null_clears_active_slot)
    test("POST /api/settings/context/activate: empty slot → 400",     test_api_settings_context_activate_rejects_empty_slot)
    test("GET /settings renders saved contexts",                      test_settings_page_renders_saved_contexts)
