"""Bounded rolling-window session history (server._load_history_messages /
_append_history / _clear_history / _get_or_create_session's `created` flag),
prepended to the Claude/OpenAI `messages` array by _stream_ai_response.

Claude's streaming call is mocked (no live API spend) with a fake that also
records the exact kwargs it was invoked with, so tests can inspect the
`messages=` array _stream_ai_response actually built."""
import asyncio
import time

_MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class _FakeAsyncStream:
    """Mimics AsyncAnthropic's streaming response shape (__aenter__/text_stream) and
    records the kwargs it was constructed with onto the shared `calls` list."""
    def __init__(self, reply_text, calls, kwargs):
        self._reply_text = reply_text
        calls.append(kwargs)

    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass

    async def _gen(self):
        yield self._reply_text

    @property
    def text_stream(self):
        return self._gen()


def _recording_stream(reply_text, calls):
    """Returns a stand-in for `async_client.messages.stream` that records every call's
    kwargs onto `calls` and always replies with `reply_text`."""
    def _stream(**kwargs):
        return _FakeAsyncStream(reply_text, calls, kwargs)
    return _stream


def register(test, skip, client):
    from database import SessionLocal
    from models import AccountLevel
    from tests.helpers import cleanup, make_user

    def _reset_capture_cooldown(uid):
        import server
        asyncio.run(server.app.state.redis.delete(f"rl:{uid}:capture:last", f"rl:{uid}:capture:count"))

    def _paid_user_with_session(db):
        u = make_user(db, AccountLevel.paid)
        u.sessions_remaining = 5
        db.commit()
        return u

    def test_window_caps_at_five():
        import server
        db = SessionLocal()
        u = None
        try:
            u = _paid_user_with_session(db)
            calls = []
            orig = server.async_client.messages.stream
            server.async_client.messages.stream = _recording_stream("reply", calls)
            try:
                for i in range(6):
                    r = client.post(
                        "/api/capture",
                        json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                        headers={"Authorization": f"Bearer {u.api_token}"},
                    )
                    assert r.status_code == 200, r.text
                    _reset_capture_cooldown(u.id)
                length = asyncio.run(server.app.state.redis.llen(server._history_key(u.id)))
                assert length == 5, f"expected window capped at 5, got {length}"
            finally:
                server.async_client.messages.stream = orig
        finally:
            cleanup(db, u)
            db.close()

    def test_historical_turns_never_carry_an_image():
        import server
        db = SessionLocal()
        u = None
        try:
            u = _paid_user_with_session(db)
            calls = []
            orig = server.async_client.messages.stream
            server.async_client.messages.stream = _recording_stream("reply", calls)
            try:
                for i in range(2):
                    r = client.post(
                        "/api/capture",
                        json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                        headers={"Authorization": f"Bearer {u.api_token}"},
                    )
                    assert r.status_code == 200, r.text
                    _reset_capture_cooldown(u.id)

                # Second call's `messages` should carry the first exchange as history,
                # followed by the current turn. Only the current (last) turn's content
                # is a list containing an image block — every earlier turn is plain text.
                second_call_messages = calls[1]["messages"]
                assert len(second_call_messages) == 3  # history user + history assistant + current user
                for turn in second_call_messages[:-1]:
                    assert isinstance(turn["content"], str), "historical turn must be text-only"
                current_content = second_call_messages[-1]["content"]
                assert isinstance(current_content, list)
                assert any(block.get("type") == "image" for block in current_content)
                # and no historical turn's text is base64 image data
                for turn in second_call_messages[:-1]:
                    assert _MINIMAL_PNG_B64 not in turn["content"]
            finally:
                server.async_client.messages.stream = orig
        finally:
            cleanup(db, u)
            db.close()

    def test_history_spans_capture_types():
        import server
        db = SessionLocal()
        u = None
        try:
            u = _paid_user_with_session(db)
            calls = []
            orig = server.async_client.messages.stream
            server.async_client.messages.stream = _recording_stream("about the two-sum problem", calls)
            try:
                r = client.post(
                    "/api/text-capture",
                    json={"text": "what's the time complexity here?", "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text
                _reset_capture_cooldown(u.id)

                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text

                screenshot_call_messages = calls[1]["messages"]
                assert screenshot_call_messages[0]["content"] == "what's the time complexity here?"
                assert screenshot_call_messages[1]["content"] == "about the two-sum problem"
            finally:
                server.async_client.messages.stream = orig
        finally:
            cleanup(db, u)
            db.close()

    def test_time_gating_skips_stale_history():
        import server
        db = SessionLocal()
        u = None
        try:
            u = _paid_user_with_session(db)
            calls = []
            orig = server.async_client.messages.stream
            server.async_client.messages.stream = _recording_stream("reply", calls)
            try:
                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text
                _reset_capture_cooldown(u.id)

                # Backdate the stored exchange's timestamp past the topic-gap threshold.
                import json as _json
                key = server._history_key(u.id)
                raw = asyncio.run(server.app.state.redis.lrange(key, 0, -1))
                entry = _json.loads(raw[0])
                entry["ts"] = time.time() - server.HISTORY_TOPIC_GAP_SECONDS - 30
                asyncio.run(server.app.state.redis.lset(key, 0, _json.dumps(entry)))

                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text

                second_call_messages = calls[1]["messages"]
                assert len(second_call_messages) == 1, "stale history should not be attached"

                # The new exchange should still have been appended afterward.
                length = asyncio.run(server.app.state.redis.llen(key))
                assert length == 2
            finally:
                server.async_client.messages.stream = orig
        finally:
            cleanup(db, u)
            db.close()

    def test_reply_truncated_before_storage():
        import server
        db = SessionLocal()
        u = None
        try:
            u = _paid_user_with_session(db)
            long_reply = "x" * (server.HISTORY_REPLY_MAX_CHARS + 500)
            calls = []
            orig = server.async_client.messages.stream
            server.async_client.messages.stream = _recording_stream(long_reply, calls)
            try:
                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text

                import json as _json
                raw = asyncio.run(server.app.state.redis.lrange(server._history_key(u.id), 0, -1))
                entry = _json.loads(raw[0])
                assert len(entry["a"]) == server.HISTORY_REPLY_MAX_CHARS
            finally:
                server.async_client.messages.stream = orig
        finally:
            cleanup(db, u)
            db.close()

    def test_history_clears_on_new_session_not_on_reuse():
        import server
        from datetime import datetime, timedelta
        from models import InterviewSession
        db = SessionLocal()
        u = None
        try:
            u = _paid_user_with_session(db)
            calls = []
            orig = server.async_client.messages.stream
            server.async_client.messages.stream = _recording_stream("reply", calls)
            try:
                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text
                key = server._history_key(u.id)
                assert asyncio.run(server.app.state.redis.llen(key)) == 1
                _reset_capture_cooldown(u.id)

                # Reusing the still-active session must NOT clear history.
                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text
                assert asyncio.run(server.app.state.redis.llen(key)) == 2
                _reset_capture_cooldown(u.id)

                # Expire the session and give another one to purchase — the next capture
                # must create a genuinely new session and clear history.
                db.query(InterviewSession).filter(InterviewSession.user_id == u.id).update(
                    {"expires_at": datetime.utcnow() - timedelta(minutes=1)}
                )
                u.sessions_remaining = 5
                db.commit()

                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text
                assert asyncio.run(server.app.state.redis.llen(key)) == 1, "history should have been cleared for the new session"
            finally:
                server.async_client.messages.stream = orig
        finally:
            cleanup(db, u)
            db.close()

    def test_max_exchanges_zero_disables_history():
        import server
        db = SessionLocal()
        u = None
        try:
            u = _paid_user_with_session(db)
            calls = []
            orig = server.async_client.messages.stream
            orig_max = server.HISTORY_MAX_EXCHANGES
            server.async_client.messages.stream = _recording_stream("reply", calls)
            server.HISTORY_MAX_EXCHANGES = 0
            try:
                for i in range(2):
                    r = client.post(
                        "/api/capture",
                        json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                        headers={"Authorization": f"Bearer {u.api_token}"},
                    )
                    assert r.status_code == 200, r.text
                    _reset_capture_cooldown(u.id)

                assert asyncio.run(server.app.state.redis.llen(server._history_key(u.id))) == 0
                for call in calls:
                    assert len(call["messages"]) == 1, "history disabled — every call should be single-turn"
            finally:
                server.async_client.messages.stream = orig
                server.HISTORY_MAX_EXCHANGES = orig_max
        finally:
            cleanup(db, u)
            db.close()

    test("Rolling window caps at 5 exchanges",                          test_window_caps_at_five)
    test("Historical turns never resend an image",                     test_historical_turns_never_carry_an_image)
    test("History spans screenshot/text/audio capture types",          test_history_spans_capture_types)
    test("Time-gating skips history past the topic-gap threshold",     test_time_gating_skips_stale_history)
    test("Stored replies are truncated before being written to history", test_reply_truncated_before_storage)
    test("History clears on a new session, not on session reuse",      test_history_clears_on_new_session_not_on_reuse)
    test("HISTORY_MAX_EXCHANGES = 0 disables history entirely",        test_max_exchanges_zero_disables_history)
