"""Provider failover: Claude -> OpenAI vision (server._stream_ai_response), and
Whisper -> Deepgram (in /api/audio-capture). Both primaries are mocked to fail so these
run without live keys; the fallback call itself is also mocked (no real Deepgram/OpenAI
vision spend in CI)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

_MINIMAL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _raise(*args, **kwargs):
    raise RuntimeError("provider unavailable")


class _FakeOpenAIStream:
    """Mimics AsyncOpenAI's streaming chat-completion response — async-iterable of chunks,
    each with the same .choices[0].delta.content shape _stream_ai_response reads."""
    def __init__(self, pieces):
        self._pieces = pieces

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for piece in self._pieces:
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=piece))])


def register(test, skip, client):
    from database import SessionLocal
    from models import AccountLevel
    from tests.helpers import cleanup, make_user

    def test_claude_failure_falls_over_to_openai():
        from auth import create_token
        import server
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            session_token = create_token(u.id)
            r = client.post("/api/trial/start", cookies={"session": session_token})
            assert r.status_code == 200

            orig_stream = server.async_client.messages.stream
            orig_openai = server.openai_async_client.chat.completions.create
            server.async_client.messages.stream = _raise
            server.openai_async_client.chat.completions.create = AsyncMock(
                return_value=_FakeOpenAIStream(["fallback ", "answer"])
            )
            try:
                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text
                server.openai_async_client.chat.completions.create.assert_called_once()
                _, kwargs = server.openai_async_client.chat.completions.create.call_args
                assert kwargs["model"] == server._OPENAI_VISION_MODEL
                assert kwargs["stream"] is True
            finally:
                server.async_client.messages.stream = orig_stream
                server.openai_async_client.chat.completions.create = orig_openai
        finally:
            cleanup(db, u)
            db.close()

    def test_whisper_failure_falls_over_to_deepgram_when_configured():
        import server
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)

            orig_whisper = server.openai_client.audio.transcriptions.create
            orig_deepgram_key = server.DEEPGRAM_API_KEY
            orig_deepgram_fn = server._deepgram_transcribe
            orig_stream = server.async_client.messages.stream

            server.openai_client.audio.transcriptions.create = _raise
            server.DEEPGRAM_API_KEY = "dg_test_key"
            server._deepgram_transcribe = MagicMock(return_value="deepgram transcript")
            server.async_client.messages.stream = lambda *a, **k: _FakeAsyncStream()
            try:
                r = client.post(
                    "/api/audio-capture",
                    files={"audio": ("rec.wav", b"fake-bytes", "audio/wav")},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text
                server._deepgram_transcribe.assert_called_once()
            finally:
                server.openai_client.audio.transcriptions.create = orig_whisper
                server.DEEPGRAM_API_KEY = orig_deepgram_key
                server._deepgram_transcribe = orig_deepgram_fn
                server.async_client.messages.stream = orig_stream
        finally:
            cleanup(db, u)
            db.close()

    class _FakeAsyncStream:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

        async def _gen(self):
            yield "ok"

        @property
        def text_stream(self):
            return self._gen()

    def test_openai_fallback_carries_history_prefix():
        """When Claude fails over to OpenAI mid-session, the accumulated rolling-window
        history must still be prepended to the OpenAI messages array — the failover
        doesn't get to silently drop context just because the provider changed."""
        import server
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            u.sessions_remaining = 5
            db.commit()

            orig_stream = server.async_client.messages.stream
            orig_openai = server.openai_async_client.chat.completions.create
            try:
                # First capture: Claude succeeds, seeding one history exchange.
                server.async_client.messages.stream = lambda *a, **k: _FakeAsyncStream()
                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text
                asyncio.run(server.app.state.redis.delete(f"rl:{u.id}:capture:last", f"rl:{u.id}:capture:count"))

                # Second capture: Claude fails, falls over to OpenAI — history should
                # still be attached ahead of the current turn.
                server.async_client.messages.stream = _raise
                server.openai_async_client.chat.completions.create = AsyncMock(
                    return_value=_FakeOpenAIStream(["fallback ", "answer"])
                )
                r = client.post(
                    "/api/capture",
                    json={"image": _MINIMAL_PNG_B64, "complexity": 2, "monitor": "browser"},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 200, r.text
                _, kwargs = server.openai_async_client.chat.completions.create.call_args
                assert len(kwargs["messages"]) == 3  # history user + history assistant + current user
                assert kwargs["messages"][0]["role"] == "user"
                assert kwargs["messages"][1]["role"] == "assistant"
            finally:
                server.async_client.messages.stream = orig_stream
                server.openai_async_client.chat.completions.create = orig_openai
        finally:
            cleanup(db, u)
            db.close()

    test("Claude failure falls over to OpenAI vision",                 test_claude_failure_falls_over_to_openai)
    test("Whisper failure falls over to Deepgram when configured",     test_whisper_failure_falls_over_to_deepgram_when_configured)
    test("OpenAI fallback still carries the history prefix",           test_openai_fallback_carries_history_prefix)
