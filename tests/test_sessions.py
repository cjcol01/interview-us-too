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

    test("Session created on first hotkey press",      test_session_created_on_first_capture)
    test("Active session reused within 2.5hr window",  test_session_reused_within_window)
    test("New session created after expiry",           test_new_session_after_expiry)
    test("Session duration is exactly 2h30m",          test_session_duration_is_2h30m)
