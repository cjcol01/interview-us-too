def register(test, skip, client):
    from auth import create_token
    from database import SessionLocal
    from models import AccountLevel, ResponseStyle
    from server import RESPONSE_STYLE_DEFAULT, _user_response_style
    from tests.helpers import cleanup, make_user

    # -- Helper / default behaviour ------------------------------------------

    def test_user_response_style_defaults_to_conversational():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            assert _user_response_style(u) == RESPONSE_STYLE_DEFAULT
            assert _user_response_style(u) == ResponseStyle.conversational
        finally:
            cleanup(db, u); db.close()

    # -- POST /api/settings/style  (Bearer token, extension-facing) ----------

    def test_api_settings_style_bearer_persists():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.post(
                "/api/settings/style",
                json={"style": "bullets"},
                headers={"Authorization": f"Bearer {u.api_token}"},
            )
            assert r.status_code == 200
            assert r.json() == {"status": "ok", "style": "bullets"}
            db.refresh(u)
            assert u.response_style == ResponseStyle.bullets
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_style_invalid_value_returns_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.post(
                "/api/settings/style",
                json={"style": "not_a_style"},
                headers={"Authorization": f"Bearer {u.api_token}"},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_style_requires_bearer():
        r = client.post("/api/settings/style", json={"style": "bullets"})
        assert r.status_code in (401, 403)

    # -- POST /api/settings/response-style  (cookie, web-facing) -------------

    def test_api_settings_response_style_cookie_persists():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/response-style",
                json={"style": "summary"},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.response_style == ResponseStyle.summary
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_response_style_requires_session():
        r = client.post("/api/settings/response-style", json={"style": "bullets"})
        assert r.status_code in (401, 403)

    # -- /api/me reflects response_style -------------------------------------

    def test_api_me_returns_response_style_field():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
            body = r.json()
            assert "response_style" in body
            assert body["response_style"] == ResponseStyle.conversational.value
        finally:
            cleanup(db, u); db.close()

    def test_api_me_reflects_saved_style():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            client.post(
                "/api/settings/response-style",
                json={"style": "one_liner"},
                cookies={"session": token},
            )
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
            assert r.json()["response_style"] == "one_liner"
        finally:
            cleanup(db, u); db.close()

    # -- POST /api/settings/complexity  (Bearer token, extension-facing) -----

    def test_api_settings_complexity_bearer_sets_value():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.post(
                "/api/settings/complexity",
                json={"value": 3},
                headers={"Authorization": f"Bearer {u.api_token}"},
            )
            assert r.status_code == 200
            assert r.json() == {"complexity": 3}
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_complexity_bearer_requires_auth():
        r = client.post("/api/settings/complexity", json={"value": 2})
        assert r.status_code in (401, 403)

    def test_api_settings_complexity_bearer_rejects_out_of_range():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.post(
                "/api/settings/complexity",
                json={"value": 0},
                headers={"Authorization": f"Bearer {u.api_token}"},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    # -- Comment level (Redis-backed, same shape as complexity) --------------

    def test_api_me_comment_level_defaults_to_high():
        from server import COMMENT_LEVEL_DEFAULT
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert r.status_code == 200
            assert r.json()["comment_level"] == COMMENT_LEVEL_DEFAULT == 2
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_comment_level_bearer_sets_value():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.post(
                "/api/settings/comment-level",
                json={"value": 3},
                headers={"Authorization": f"Bearer {u.api_token}"},
            )
            assert r.status_code == 200
            assert r.json() == {"comment_level": 3}
            me = client.get("/api/me", headers={"Authorization": f"Bearer {u.api_token}"})
            assert me.json()["comment_level"] == 3
        finally:
            cleanup(db, u); db.close()

    def test_api_settings_comment_level_bearer_requires_auth():
        r = client.post("/api/settings/comment-level", json={"value": 2})
        assert r.status_code in (401, 403)

    def test_api_settings_comment_level_rejects_out_of_range():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            r = client.post(
                "/api/settings/comment-level",
                json={"value": 4},
                headers={"Authorization": f"Bearer {u.api_token}"},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u); db.close()

    def test_settings_comment_level_stepper_clamps():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            # Default is 2, so one step down hits the floor and a second must stay there
            r = client.post("/settings/comment-level/down", cookies={"session": token})
            assert r.status_code == 200 and r.json() == {"comment_level": 1}
            r = client.post("/settings/comment-level/down", cookies={"session": token})
            assert r.json() == {"comment_level": 1}
            for expected in (2, 3, 3):
                r = client.post("/settings/comment-level/up", cookies={"session": token})
                assert r.json() == {"comment_level": expected}
        finally:
            cleanup(db, u); db.close()

    def test_settings_comment_level_stepper_requires_subscription():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.free)
            token = create_token(u.id)
            r = client.post("/settings/comment-level/up", cookies={"session": token})
            assert r.status_code == 403
        finally:
            cleanup(db, u); db.close()

    def test_every_comment_level_has_wording():
        from server import COMMENT_LEVEL_MAX, COMMENT_LEVEL_MIN, COMMENT_LEVEL_SUFFIX
        for level in range(COMMENT_LEVEL_MIN, COMMENT_LEVEL_MAX + 1):
            assert COMMENT_LEVEL_SUFFIX[level].startswith("\n\nComment level:")

    test("_user_response_style defaults to conversational",         test_user_response_style_defaults_to_conversational)
    test("POST /api/settings/style (Bearer) persists style",        test_api_settings_style_bearer_persists)
    test("POST /api/settings/style: invalid value → 422",          test_api_settings_style_invalid_value_returns_422)
    test("POST /api/settings/style requires Bearer token",          test_api_settings_style_requires_bearer)
    test("POST /api/settings/response-style (cookie) persists",     test_api_settings_response_style_cookie_persists)
    test("POST /api/settings/response-style requires session",      test_api_settings_response_style_requires_session)
    test("/api/me includes response_style field",                   test_api_me_returns_response_style_field)
    test("/api/me reflects saved response style",                   test_api_me_reflects_saved_style)
    test("POST /api/settings/complexity (Bearer) sets value",       test_api_settings_complexity_bearer_sets_value)
    test("POST /api/settings/complexity requires Bearer token",     test_api_settings_complexity_bearer_requires_auth)
    test("POST /api/settings/complexity: out-of-range → 422",      test_api_settings_complexity_bearer_rejects_out_of_range)
    test("/api/me comment_level defaults to 2 (high)",              test_api_me_comment_level_defaults_to_high)
    test("POST /api/settings/comment-level (Bearer) sets value",    test_api_settings_comment_level_bearer_sets_value)
    test("POST /api/settings/comment-level requires Bearer token",  test_api_settings_comment_level_bearer_requires_auth)
    test("POST /api/settings/comment-level: out-of-range → 422",   test_api_settings_comment_level_rejects_out_of_range)
    test("/settings/comment-level/{up,down} clamps to 1..3",        test_settings_comment_level_stepper_clamps)
    test("/settings/comment-level requires a subscription",         test_settings_comment_level_stepper_requires_subscription)
    test("every comment level has prompt wording",                  test_every_comment_level_has_wording)
