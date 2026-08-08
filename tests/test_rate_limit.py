import asyncio
import secrets as _sec

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


def register(test, skip, client):
    from fastapi import HTTPException

    def test_rate_limit_cooldown_branch_raises_429():
        """Calling _rate_limit twice immediately (within `cooldown` seconds) raises 429."""
        import server
        uid = _sec.randbits(31)

        async def _run():
            r = server.app.state.redis
            await server._rate_limit(r, uid, "rl_unit_cooldown", cooldown=5, limit=100)
            try:
                await server._rate_limit(r, uid, "rl_unit_cooldown", cooldown=5, limit=100)
                return False
            except HTTPException as e:
                return e.status_code == 429
            finally:
                await r.delete(f"rl:{uid}:rl_unit_cooldown:last", f"rl:{uid}:rl_unit_cooldown:count")

        assert asyncio.run(_run())

    def test_rate_limit_count_branch_raises_429():
        """With cooldown=0 (never blocks), exceeding `limit` calls in the same window raises 429."""
        import server
        uid = _sec.randbits(31)

        async def _run():
            r = server.app.state.redis
            for _ in range(3):
                await server._rate_limit(r, uid, "rl_unit_count", cooldown=0, limit=3)
            try:
                await server._rate_limit(r, uid, "rl_unit_count", cooldown=0, limit=3)
                return False
            except HTTPException as e:
                return e.status_code == 429
            finally:
                await r.delete(f"rl:{uid}:rl_unit_count:last", f"rl:{uid}:rl_unit_count:count")

        assert asyncio.run(_run())

    def test_rate_limit_window_branch_raises_429():
        """With cooldown=0 and a per-minute `limit` high enough to never trigger, exceeding
        `window_limit` calls within `window_seconds` raises 429 with the window message."""
        import server
        uid = _sec.randbits(31)

        async def _run():
            r = server.app.state.redis
            for _ in range(3):
                await server._rate_limit(r, uid, "rl_unit_window", cooldown=0, limit=1000, window_limit=3)
            try:
                await server._rate_limit(r, uid, "rl_unit_window", cooldown=0, limit=1000, window_limit=3)
                return False
            except HTTPException as e:
                return e.status_code == 429
            finally:
                await r.delete(
                    f"rl:{uid}:rl_unit_window:last",
                    f"rl:{uid}:rl_unit_window:count",
                    f"rl:{uid}:rl_unit_window:window_count",
                )

        assert asyncio.run(_run())

    def test_record_usage_increments_same_day_row():
        from database import SessionLocal
        from models import AccountLevel, UsageDaily
        from tests.helpers import cleanup, make_user
        import server

        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            server._record_usage(db, u.id, "capture")
            server._record_usage(db, u.id, "capture")
            server._record_usage(db, u.id, "audio")

            row = db.query(UsageDaily).filter(UsageDaily.user_id == u.id).first()
            assert row is not None
            assert row.capture_count == 2
            assert row.audio_count == 1
        finally:
            cleanup(db, u)
            db.close()

    test("_rate_limit: cooldown window raises 429",   test_rate_limit_cooldown_branch_raises_429)
    test("_rate_limit: per-minute count raises 429",  test_rate_limit_count_branch_raises_429)
    test("_rate_limit: window_limit tier raises 429", test_rate_limit_window_branch_raises_429)
    test("_record_usage: increments same-day row",    test_record_usage_increments_same_day_row)

    # -- Integration: unauthenticated endpoints -------------------------------

    def test_login_retry_is_immediate_but_bounded():
        """Login has no per-attempt cooldown — retyping a fumbled password straight away must
        reach the credential check, not a 429. Guessing is bounded by the per-minute ceiling
        (10 on the identity), which is what eventually returns 429."""
        import server
        uname = f"_test_login_rl_{_sec.token_hex(4)}"
        body = {"username": uname, "password": "wrongpassword"}

        async def _clear_ip():
            # The per-IP limiter (20/min) is keyed on "testclient" and shared with every other
            # test in the suite, so clear it or this test's own burst 429s on the wrong axis.
            r = server.app.state.redis
            await r.delete(
                "rl:testclient:login_ip:last",
                "rl:testclient:login_ip:count",
                "rl:testclient:login_ip:window_count",
            )

        asyncio.run(_clear_ip())
        # Ten back-to-back attempts, no pause: every one gets a real answer (401 for this
        # nonexistent account) rather than being turned away by a throttle.
        for _ in range(10):
            asyncio.run(_clear_ip())
            assert client.post("/auth/login", json=body).status_code == 401
        # The eleventh in the same minute is over the identity's ceiling.
        asyncio.run(_clear_ip())
        assert client.post("/auth/login", json=body).status_code == 429

    def test_login_success_clears_identity_budget():
        """A correct password releases the identity's spent budget, so fumbling a couple of
        times and then getting it right doesn't leave the next sign-in pre-throttled."""
        from database import SessionLocal
        from models import AccountLevel
        from tests.helpers import cleanup, make_user
        import server

        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            from auth import hash_password
            u.password_hash = hash_password("testpass123")
            db.commit()
            identity = u.username.lower()

            async def _counts():
                r = server.app.state.redis
                return (await r.get(f"rl:{identity}:login_user:count"),
                        await r.get(f"rl:{identity}:login_user:window_count"))

            for _ in range(3):
                assert client.post("/auth/login", json={"username": u.username, "password": "nope"}).status_code == 401
            assert asyncio.run(_counts())[0] is not None      # the fumbles were counted
            assert client.post("/auth/login", json={"username": u.username, "password": "testpass123"}).status_code == 200
            assert asyncio.run(_counts()) == (None, None)     # ...and the success wiped them
        finally:
            cleanup(db, u)
            db.close()

    def test_register_rapid_calls_hit_cooldown_429():
        from tests.helpers import delete_by_name

        uname1 = f"_test_reg_rl_{_sec.token_hex(4)}"
        uname2 = f"_test_reg_rl_{_sec.token_hex(4)}"
        try:
            first = client.post("/auth/register", json={
                "full_name": "RL Test", "username": uname1,
                "email": f"{uname1}@test.internal", "password": "TestPass123!",
            })
            second = client.post("/auth/register", json={
                "full_name": "RL Test", "username": uname2,
                "email": f"{uname2}@test.internal", "password": "TestPass123!",
            })
            assert first.status_code == 200
            # IP-keyed cooldown (1s) — second rapid signup from the same connection is blocked
            # before it ever reaches the username/email uniqueness checks.
            assert second.status_code == 429
        finally:
            delete_by_name(uname1)
            delete_by_name(uname2)

    def test_forgot_password_rapid_calls_hit_cooldown_429():
        email = f"_test_fp_rl_{_sec.token_hex(4)}@test.internal"
        first = client.post("/auth/forgot-password", json={"email": email})
        second = client.post("/auth/forgot-password", json={"email": email})
        # Email-keyed cooldown (30s) fires on the second call regardless of whether the
        # email belongs to a real account.
        assert first.status_code == 200
        assert second.status_code == 429

    def test_resend_verification_rapid_calls_hit_cooldown_429():
        from auth import create_token
        from database import SessionLocal
        from models import AccountLevel
        from tests.helpers import cleanup, make_user

        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            u.email_verified = False
            db.commit()
            token = create_token(u.id)
            first = client.post("/auth/resend-verification", cookies={"session": token})
            second = client.post("/auth/resend-verification", cookies={"session": token})
            # User-keyed cooldown (30s) fires on the second call.
            assert first.status_code == 200
            assert second.status_code == 429
        finally:
            cleanup(db, u)
            db.close()

    test("POST /auth/login: immediate retry allowed, ceiling still 429",   test_login_retry_is_immediate_but_bounded)
    test("POST /auth/login: success clears the identity's limiter budget", test_login_success_clears_identity_budget)
    test("POST /auth/register: rapid calls hit cooldown -> 429",           test_register_rapid_calls_hit_cooldown_429)
    test("POST /auth/forgot-password: rapid calls hit cooldown -> 429",    test_forgot_password_rapid_calls_hit_cooldown_429)
    test("POST /auth/resend-verification: rapid calls hit cooldown -> 429", test_resend_verification_rapid_calls_hit_cooldown_429)

    # -- Integration: /api/capture rate limiting ------------------------------

    def test_capture_rapid_calls_hit_cooldown_429():
        from auth import create_token
        from database import SessionLocal
        from models import AccountLevel
        from tests.helpers import cleanup, make_user

        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            session_token = create_token(u.id)
            r = client.post("/api/trial/start", cookies={"session": session_token})
            assert r.status_code == 200

            import server
            orig = server.async_client.messages.stream
            server.async_client.messages.stream = _mock_anthropic_stream
            try:
                capture_args = dict(
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                first = client.post("/api/capture", **capture_args)
                assert first.status_code == 200
                second = client.post("/api/capture", **capture_args)
                assert second.status_code == 429
            finally:
                server.async_client.messages.stream = orig
        finally:
            cleanup(db, u)
            db.close()

    test("POST /api/capture: rapid calls hit cooldown -> 429", test_capture_rapid_calls_hit_cooldown_429)

    def test_audio_rapid_calls_hit_cooldown_429():
        from database import SessionLocal
        from models import AccountLevel
        from tests.helpers import cleanup, fake_audio_bytes, make_user

        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)

            import server

            def _raise(*args, **kwargs):
                raise RuntimeError("Whisper unavailable")

            orig = server.openai_client.audio.transcriptions.create
            # Force no Deepgram fallback configured — otherwise a real DEEPGRAM_API_KEY in
            # this checkout's .env would let the first call succeed via failover instead of 500.
            orig_deepgram_key = server.DEEPGRAM_API_KEY
            server.openai_client.audio.transcriptions.create = _raise
            server.DEEPGRAM_API_KEY = ""
            try:
                audio_args = dict(
                    files={"audio": ("rec.webm", fake_audio_bytes(), "audio/webm")},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                first = client.post("/api/audio-capture", **audio_args)
                second = client.post("/api/audio-capture", **audio_args)
                assert first.status_code == 500
                assert second.status_code == 429
            finally:
                server.openai_client.audio.transcriptions.create = orig
                server.DEEPGRAM_API_KEY = orig_deepgram_key
        finally:
            cleanup(db, u)
            db.close()

    test("POST /api/audio-capture: rapid calls hit cooldown -> 429", test_audio_rapid_calls_hit_cooldown_429)
