import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# A spoken interview question, not a "hello": the endpoint now drops clips with no actual
# speech in them, and the old one-word fixture transcribed to exactly the kind of thing that
# filter exists to throw away (see _transcript_has_no_speech in server.py).
FIXTURE = Path(__file__).parent / "fixtures" / "interview_question.wav"


def register(test, skip, client):
    from config import ANTHROPIC_API_KEY, OPENAI_API_KEY
    from database import SessionLocal
    from models import AccountLevel, InterviewSession
    from tests.helpers import cleanup, fake_audio_bytes, make_user

    live_ok = (
        OPENAI_API_KEY
        and not OPENAI_API_KEY.startswith("sk-...")
        and ANTHROPIC_API_KEY
        and not ANTHROPIC_API_KEY.startswith("sk-ant-...")
        and FIXTURE.exists()
    )

    def test_free_user_is_blocked():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.free)
            r = client.post(
                "/api/audio-capture",
                files={"audio": ("rec.webm", b"fake", "audio/webm")},
                headers={"Authorization": f"Bearer {u.api_token}"},
            )
            assert r.status_code == 403
        finally:
            cleanup(db, u)
            db.close()

    def test_trial_without_active_session_is_blocked():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            # no InterviewSession exists → should broadcast trial_expired and return 403
            r = client.post(
                "/api/audio-capture",
                files={"audio": ("rec.webm", b"fake", "audio/webm")},
                headers={"Authorization": f"Bearer {u.api_token}"},
            )
            assert r.status_code == 403
            assert "trial_expired" in r.json().get("detail", "")
        finally:
            cleanup(db, u)
            db.close()

    def test_invalid_token_is_401():
        r = client.post(
            "/api/audio-capture",
            files={"audio": ("rec.webm", b"fake", "audio/webm")},
            headers={"Authorization": "Bearer notavalidtoken"},
        )
        assert r.status_code == 401

    def test_missing_audio_field_is_422():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            r = client.post(
                "/api/audio-capture",
                headers={"Authorization": f"Bearer {u.api_token}"},
            )
            assert r.status_code == 422
        finally:
            cleanup(db, u)
            db.close()

    def test_whisper_failure_returns_500():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            import server
            original = server.openai_client.audio.transcriptions.create
            # Force no Deepgram fallback configured — otherwise a real DEEPGRAM_API_KEY in
            # this checkout's .env would let the request succeed via failover instead of 500.
            orig_deepgram_key = server.DEEPGRAM_API_KEY

            def _raise(*args, **kwargs):
                raise RuntimeError("Whisper unavailable")

            server.openai_client.audio.transcriptions.create = _raise
            server.DEEPGRAM_API_KEY = ""
            try:
                r = client.post(
                    "/api/audio-capture",
                    files={"audio": ("rec.wav", fake_audio_bytes(), "audio/wav")},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 500
            finally:
                server.openai_client.audio.transcriptions.create = original
                server.DEEPGRAM_API_KEY = orig_deepgram_key
        finally:
            cleanup(db, u)
            db.close()

    def test_silent_transcript_helper():
        from server import _transcript_has_no_speech
        # Whisper's stock hallucinations over silence, plus genuinely empty results.
        for silent in ("", "   ", ".", "you", "Thank you.", "Thanks for watching!", "Bye.",
                       "Thank you. Thank you.", "Uh, so, um, yeah", "[ Silence ]"):
            assert _transcript_has_no_speech(silent), f"expected no-speech: {silent!r}"
        for speech in ("Explain BFS", "Why SQL?", "What is the time complexity?",
                       "Tell me about yourself.", "So, why do you want to work here?",
                       "yes yes yes yes yes yes yes yes yes"):
            assert not _transcript_has_no_speech(speech), f"expected speech: {speech!r}"

    def test_silent_clip_skips_the_ai_call():
        """A near-silent clip transcribes to a hallucinated "Thank you." — the endpoint must
        stop there instead of streaming a confident answer to a question nobody asked."""
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.paid)
            import server
            with patch.object(server.openai_client.audio.transcriptions, "create",
                              return_value=MagicMock(text="Thank you.")), \
                 patch.object(server, "_stream_ai_response") as stream:
                r = client.post(
                    "/api/audio-capture",
                    files={"audio": ("rec.wav", fake_audio_bytes(), "audio/wav")},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
            assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
            assert r.json() == {"status": "no-speech"}, f"json={r.json()}"
            assert not stream.called, "AI was called for a clip with no speech in it"
        finally:
            cleanup(db, u)
            db.close()

    def test_paid_happy_path_live():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            with open(FIXTURE, "rb") as f:
                audio_bytes = f.read()
            r = client.post(
                "/api/audio-capture",
                files={"audio": ("interview_question.wav", audio_bytes, "audio/wav")},
                headers={"Authorization": f"Bearer {u.api_token}"},
                timeout=60,
            )
            assert r.status_code == 200, f"status={r.status_code} body={r.text[:300]}"
            assert r.json() == {"status": "ok"}, f"json={r.json()}"
        finally:
            cleanup(db, u)
            db.close()

    test("Free user blocked from /api/audio-capture (403)",      test_free_user_is_blocked)
    test("Trial user without session blocked (trial_expired)",   test_trial_without_active_session_is_blocked)
    test("Invalid token → 401",                                  test_invalid_token_is_401)
    test("Missing audio field → 422",                            test_missing_audio_field_is_422)
    test("Whisper failure returns 500",                          test_whisper_failure_returns_500)
    test("_transcript_has_no_speech separates silence from speech", test_silent_transcript_helper)
    test("Silent clip skips the AI call (no-speech)",            test_silent_clip_skips_the_ai_call)

    if live_ok:
        test("Paid user audio capture end-to-end (live API)",   test_paid_happy_path_live)
    else:
        skip("Paid user audio capture end-to-end (live API)",   "OPENAI_API_KEY or ANTHROPIC_API_KEY not configured")
