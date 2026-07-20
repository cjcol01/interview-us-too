def register(test, skip, client):
    from auth import create_token, verify_password
    from database import SessionLocal
    from models import AccountLevel
    from tests.helpers import cleanup, make_user

    # -- POST /api/settings/account -------------------------------------------

    def test_update_full_name_persists():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/account",
                json={"full_name": "New Name"},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.full_name == "New Name"
        finally:
            cleanup(db, u); db.close()

    def test_update_username_persists_with_correct_password():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            new_username = u.username + "_renamed"
            r = client.post(
                "/api/settings/account",
                json={"username": new_username, "current_password": "testpass123"},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.username == new_username
        finally:
            cleanup(db, u); db.close()

    def test_update_username_rejects_missing_password():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            original_username = u.username
            r = client.post(
                "/api/settings/account",
                json={"username": original_username + "_renamed"},
                cookies={"session": token},
            )
            assert r.status_code == 400
            db.refresh(u)
            assert u.username == original_username
        finally:
            cleanup(db, u); db.close()

    def test_update_username_rejects_wrong_password():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            original_username = u.username
            r = client.post(
                "/api/settings/account",
                json={"username": original_username + "_renamed", "current_password": "notthepassword"},
                cookies={"session": token},
            )
            assert r.status_code == 400
            db.refresh(u)
            assert u.username == original_username
        finally:
            cleanup(db, u); db.close()

    def test_update_rejects_duplicate_username():
        db = SessionLocal()
        try:
            u1 = make_user(db, AccountLevel.trial)
            u2 = make_user(db, AccountLevel.trial)
            token = create_token(u2.id)
            r = client.post(
                "/api/settings/account",
                json={"username": u1.username, "current_password": "testpass123"},
                cookies={"session": token},
            )
            assert r.status_code == 400
        finally:
            cleanup(db, u1, u2); db.close()

    def test_update_account_ignores_email_field():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            original_email = u.email
            token = create_token(u.id)
            r = client.post(
                "/api/settings/account",
                json={"email": "someone-else@test.internal"},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert u.email == original_email
        finally:
            cleanup(db, u); db.close()

    def test_update_account_requires_auth():
        r = client.post("/api/settings/account", json={"full_name": "Nobody"})
        assert r.status_code == 401

    test("POST /api/settings/account: full_name persists",              test_update_full_name_persists)
    test("POST /api/settings/account: username persists w/ password",   test_update_username_persists_with_correct_password)
    test("POST /api/settings/account: username change needs password",  test_update_username_rejects_missing_password)
    test("POST /api/settings/account: username change wrong password",  test_update_username_rejects_wrong_password)
    test("POST /api/settings/account: duplicate username -> 400",       test_update_rejects_duplicate_username)
    test("POST /api/settings/account: email field is ignored",          test_update_account_ignores_email_field)
    test("POST /api/settings/account requires auth",                    test_update_account_requires_auth)

    # -- POST /api/settings/password ------------------------------------------

    def test_change_password_success():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/password",
                json={"current_password": "testpass123", "new_password": "newpassword456"},
                cookies={"session": token},
            )
            assert r.status_code == 200
            db.refresh(u)
            assert verify_password("newpassword456", u.password_hash)
        finally:
            cleanup(db, u); db.close()

    def test_change_password_wrong_current_rejected():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/password",
                json={"current_password": "notthepassword", "new_password": "newpassword456"},
                cookies={"session": token},
            )
            assert r.status_code == 400
        finally:
            cleanup(db, u); db.close()

    def test_change_password_too_short_rejected():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            token = create_token(u.id)
            r = client.post(
                "/api/settings/password",
                json={"current_password": "testpass123", "new_password": "short"},
                cookies={"session": token},
            )
            assert r.status_code == 400
        finally:
            cleanup(db, u); db.close()

    test("POST /api/settings/password: success changes hash",      test_change_password_success)
    test("POST /api/settings/password: wrong current -> 400",      test_change_password_wrong_current_rejected)
    test("POST /api/settings/password: new < 8 chars -> 400",      test_change_password_too_short_rejected)
