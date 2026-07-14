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

    test("_rate_limit: cooldown window raises 429",   test_rate_limit_cooldown_branch_raises_429)
    test("_rate_limit: per-minute count raises 429",  test_rate_limit_count_branch_raises_429)

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
