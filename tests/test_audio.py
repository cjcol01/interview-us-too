import os
from pathlib import Path
from unittest.mock import MagicMock, patch

FIXTURE = Path(__file__).parent / "fixtures" / "test_audio.wav"


def register(test, skip, client):
    from config import ANTHROPIC_API_KEY, OPENAI_API_KEY
    from database import SessionLocal
    from models import AccountLevel, InterviewSession
    from tests.helpers import cleanup, make_user

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

            def _raise(*args, **kwargs):
                raise RuntimeError("Whisper unavailable")

            server.openai_client.audio.transcriptions.create = _raise
            try:
                r = client.post(
                    "/api/audio-capture",
                    files={"audio": ("rec.wav", b"fake-bytes", "audio/wav")},
                    headers={"Authorization": f"Bearer {u.api_token}"},
                )
                assert r.status_code == 500
            finally:
                server.openai_client.audio.transcriptions.create = original
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
                files={"audio": ("test_audio.wav", audio_bytes, "audio/wav")},
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

    if live_ok:
        test("Paid user audio capture end-to-end (live API)",   test_paid_happy_path_live)
    else:
        skip("Paid user audio capture end-to-end (live API)",   "OPENAI_API_KEY or ANTHROPIC_API_KEY not configured")
