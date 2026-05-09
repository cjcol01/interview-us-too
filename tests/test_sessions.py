def register(test, skip, client=None):
    from database import SessionLocal, init_db
    from models import InterviewSession
    from server import _get_or_create_session
    from tests.helpers import make_user, cleanup

    def test_session_created_on_first_capture():
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            s = _get_or_create_session(db, u.id)
            assert s.id is not None
            assert s.user_id == u.id
            assert s.ended_at is None
            from datetime import datetime, timedelta
            assert s.expires_at > datetime.utcnow()
            assert s.expires_at < datetime.utcnow() + timedelta(hours=3)
        finally:
            cleanup(db, u)
            db.close()

    def test_session_reused_within_window():
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            s1 = _get_or_create_session(db, u.id)
            s2 = _get_or_create_session(db, u.id)
            assert s1.id == s2.id, "should reuse the active session"
        finally:
            cleanup(db, u)
            db.close()

    def test_new_session_after_expiry():
        from datetime import datetime, timedelta
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            s1 = _get_or_create_session(db, u.id)
            s1.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
            s2 = _get_or_create_session(db, u.id)
            assert s2.id != s1.id, "should create a new session after expiry"
        finally:
            cleanup(db, u)
            db.close()

    def test_session_duration_is_2h30m():
        from datetime import timedelta
        from server import SESSION_DURATION
        assert SESSION_DURATION == timedelta(hours=2, minutes=30)
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            s = _get_or_create_session(db, u.id)
            assert s.expires_at - s.started_at == SESSION_DURATION
        finally:
            cleanup(db, u)
            db.close()

    def test_trial_start_creates_session():
        from auth import create_token
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            token = create_token(u.id)
            r = client.post("/api/trial/start", cookies={"session": token})
            assert r.status_code == 200
            body = r.json()
            assert "started_at" in body
            assert "expires_at" in body
            assert body["seconds_remaining"] > 0
            sess = db.query(InterviewSession).filter(
                InterviewSession.user_id == u.id
            ).first()
            assert sess is not None
            from server import TRIAL_DURATION
            assert abs((sess.expires_at - sess.started_at).total_seconds()
                       - TRIAL_DURATION.total_seconds()) < 2
        finally:
            cleanup(db, u)
            db.close()

    def test_trial_start_rejected_on_non_trial():
        from auth import create_token
        from models import AccountLevel
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            token = create_token(u.id)
            r = client.post("/api/trial/start", cookies={"session": token})
            assert r.status_code == 400
        finally:
            cleanup(db, u)
            db.close()

    def test_trial_start_rejected_if_already_used():
        from auth import create_token
        from server import _get_or_create_session, TRIAL_DURATION
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            _get_or_create_session(db, u.id, TRIAL_DURATION)
            token = create_token(u.id)
            r = client.post("/api/trial/start", cookies={"session": token})
            assert r.status_code == 400
        finally:
            cleanup(db, u)
            db.close()

    def test_trial_status_before_start():
        from auth import create_token
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            token = create_token(u.id)
            r = client.get("/api/trial/status", cookies={"session": token})
            assert r.status_code == 200
            body = r.json()
            assert body["is_trial"] is True
            assert body["started"] is False
        finally:
            cleanup(db, u)
            db.close()

    def test_trial_status_after_start():
        from auth import create_token
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            token = create_token(u.id)
            client.post("/api/trial/start", cookies={"session": token})
            r = client.get("/api/trial/status", cookies={"session": token})
            assert r.status_code == 200
            body = r.json()
            assert body["is_trial"] is True
            assert body["started"] is True
            assert body["seconds_remaining"] > 0
        finally:
            cleanup(db, u)
            db.close()

    def test_setup_complete_sets_flag():
        from auth import create_token
        from models import User
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            assert u.setup_complete is False
            token = create_token(u.id)
            r = client.post("/api/setup/complete", cookies={"session": token})
            assert r.status_code == 200
            db.refresh(u)
            assert u.setup_complete is True
        finally:
            cleanup(db, u)
            db.close()

    test("Session created on first hotkey press",      test_session_created_on_first_capture)
    test("Active session reused within 2.5hr window",  test_session_reused_within_window)
    test("New session created after expiry",           test_new_session_after_expiry)
    test("Session duration is exactly 2h30m",          test_session_duration_is_2h30m)
    test("/api/trial/start creates InterviewSession",  test_trial_start_creates_session)
    test("/api/trial/start rejected for non-trial",    test_trial_start_rejected_on_non_trial)
    test("/api/trial/start rejected if already used",  test_trial_start_rejected_if_already_used)
    test("/api/trial/status before start",             test_trial_status_before_start)
    test("/api/trial/status after start",              test_trial_status_after_start)
    test("/api/setup/complete flips flag",             test_setup_complete_sets_flag)
