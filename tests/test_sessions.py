_MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class _FakeAsyncStream:
    """Minimal async context manager that mimics anthropic's streaming response."""
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass

    async def _gen(self):
        yield "ok"

    @property
    def text_stream(self):
        return self._gen()


def _mock_anthropic_stream(*args, **kwargs):
    return _FakeAsyncStream()


def register(test, skip, client=None):
    from database import SessionLocal, init_db
    from models import AccountLevel, InterviewSession
    from server import _get_or_create_session
    from tests.helpers import cleanup, make_user

    def test_session_created_on_first_capture():
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            s, created = _get_or_create_session(db, u.id)
            assert created is True
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
            s1, created1 = _get_or_create_session(db, u.id)
            s2, created2 = _get_or_create_session(db, u.id)
            assert s1.id == s2.id, "should reuse the active session"
            assert created1 is True
            assert created2 is False, "reusing an active session should report created=False"
        finally:
            cleanup(db, u)
            db.close()

    def test_new_session_after_expiry():
        from datetime import datetime, timedelta
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            s1, _ = _get_or_create_session(db, u.id)
            s1.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()
            s2, created2 = _get_or_create_session(db, u.id)
            assert s2.id != s1.id, "should create a new session after expiry"
            assert created2 is True
        finally:
            cleanup(db, u)
            db.close()

    def test_session_duration_is_1h30m():
        from datetime import timedelta
        from server import SESSION_DURATION
        assert SESSION_DURATION == timedelta(hours=1, minutes=30)
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db)
            s, _ = _get_or_create_session(db, u.id)
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
    test("Session duration is exactly 1h30m",          test_session_duration_is_1h30m)
    test("/api/trial/start creates InterviewSession",  test_trial_start_creates_session)
    test("/api/trial/start rejected for non-trial",    test_trial_start_rejected_on_non_trial)
    test("/api/trial/start rejected if already used",  test_trial_start_rejected_if_already_used)
    test("/api/trial/status before start",             test_trial_status_before_start)
    test("/api/trial/status after start",              test_trial_status_after_start)
    test("/api/setup/complete flips flag",             test_setup_complete_sets_flag)

    # -- paid account gating in /api/capture ---------------------------------

    def test_paid_no_session_deducts_sessions_remaining():
        """Paid user with sessions_remaining=2 and no active session: capture deducts one."""
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            u.sessions_remaining = 2
            db.commit()
            import server
            orig = server.async_client.messages.stream
            server.async_client.messages.stream = _mock_anthropic_stream
            try:
                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200
                db.refresh(u)
                assert u.sessions_remaining == 1
            finally:
                server.async_client.messages.stream = orig
        finally:
            cleanup(db, u); db.close()

    def test_paid_sessions_exhausted_returns_403_and_downgrades():
        """Paid user with sessions_remaining=0 and no active session: 403 + downgraded to free."""
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            u.sessions_remaining = 0
            db.commit()
            r = client.post(
                "/api/capture",
                json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                headers={"Authorization": f"Bearer {u.api_token}"},
            )
            assert r.status_code == 403
            assert "sessions_exhausted" in r.json().get("detail", "")
            db.refresh(u)
            assert u.account_level == AccountLevel.free
        finally:
            cleanup(db, u); db.close()

    def test_paid_with_active_session_no_deduction():
        """Paid user with an active session: no sessions_remaining deduction."""
        from datetime import timedelta
        from datetime import datetime
        init_db()
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            u.sessions_remaining = 2
            db.commit()
            sess = InterviewSession(
                user_id=u.id,
                expires_at=datetime.utcnow() + timedelta(hours=2),
            )
            db.add(sess); db.commit()
            import server
            orig = server.async_client.messages.stream
            server.async_client.messages.stream = _mock_anthropic_stream
            try:
                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200
                db.refresh(u)
                assert u.sessions_remaining == 2
            finally:
                server.async_client.messages.stream = orig
        finally:
            cleanup(db, u); db.close()

    test("Paid: no session, sessions=2 → deducts one",             test_paid_no_session_deducts_sessions_remaining)
    test("Paid: sessions=0, no session → 403 + downgrade to free", test_paid_sessions_exhausted_returns_403_and_downgrades)
    test("Paid: has active session → no deduction",                test_paid_with_active_session_no_deduction)
