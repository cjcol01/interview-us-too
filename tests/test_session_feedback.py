"""Post-interview feedback: POST /api/session/feedback and the reminder wiring.

Uses the custom harness (not pytest): export register(test, skip, client).
"""
from datetime import datetime, timedelta
from unittest.mock import patch

from auth import create_token
from database import SessionLocal
from models import AccountLevel, SessionFeedback, User
from tests.helpers import cleanup, make_user
from tests.test_admin import _make_admin_cookie


def _cookie(user):
    return create_token(user.id)


def _utc_today():
    """The server validates and sweeps interview dates against datetime.utcnow().date(), so the
    tests have to reckon from the same clock. Using date.today() here made "yesterday" and
    "tomorrow" mean different days to the test and to the server whenever the machine's local
    date was ahead of UTC — so these tests failed for the hour after local midnight in BST, and
    would fail far more widely anywhere further east."""
    return datetime.utcnow().date()


def register(test, skip, client):

    def test_valid_submit_persists_row():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.paid)
            r = client.post(
                "/api/session/feedback",
                json={"rating": 4, "comment": "Great session", "answer_count": 5, "duration_seconds": 400},
                cookies={"session": _cookie(u)},
            )
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "ok"
            row = db.query(SessionFeedback).filter(SessionFeedback.user_id == u.id).first()
            assert row is not None
            assert row.rating == 4
            assert row.comment == "Great session"
            assert row.answer_count == 5
            assert row.duration_seconds == 400
        finally:
            cleanup(db, u)
            db.close()

    def test_rating_zero_rejected():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.paid)
            r = client.post(
                "/api/session/feedback",
                json={"rating": 0},
                cookies={"session": _cookie(u)},
            )
            assert r.status_code == 422, r.text
        finally:
            cleanup(db, u)
            db.close()

    def test_rating_six_rejected():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.paid)
            r = client.post(
                "/api/session/feedback",
                json={"rating": 6},
                cookies={"session": _cookie(u)},
            )
            assert r.status_code == 422, r.text
        finally:
            cleanup(db, u)
            db.close()

    def test_next_interview_date_sets_user_date_and_rearms_reminder():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.paid)
            tomorrow = (_utc_today() + timedelta(days=1)).isoformat()
            r = client.post(
                "/api/session/feedback",
                json={"rating": 3, "next_interview_date": tomorrow},
                cookies={"session": _cookie(u)},
            )
            assert r.status_code == 200, r.text
            db.refresh(u)
            assert u.interview_date is not None
            assert u.interview_date.isoformat() == tomorrow
            assert u.interview_reminder_sent is False
        finally:
            cleanup(db, u)
            db.close()

    def test_same_date_does_not_rearm_already_sent_reminder():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.paid)
            tomorrow = _utc_today() + timedelta(days=1)
            u.interview_date = tomorrow
            u.interview_reminder_sent = True
            db.commit()
            r = client.post(
                "/api/session/feedback",
                json={"rating": 5, "next_interview_date": tomorrow.isoformat()},
                cookies={"session": _cookie(u)},
            )
            assert r.status_code == 200, r.text
            db.refresh(u)
            # Same date — reminder_sent must stay True (no re-arm)
            assert u.interview_reminder_sent is True
        finally:
            cleanup(db, u)
            db.close()

    def test_past_date_rejected():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.paid)
            yesterday = (_utc_today() - timedelta(days=1)).isoformat()
            r = client.post(
                "/api/session/feedback",
                json={"rating": 2, "next_interview_date": yesterday},
                cookies={"session": _cookie(u)},
            )
            assert r.status_code == 400, r.text
        finally:
            cleanup(db, u)
            db.close()

    def test_reminder_picks_up_user_with_date_tomorrow():
        import server as _s
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.paid)
            u.interview_date = _utc_today() + timedelta(days=1)
            u.interview_reminder_sent = False
            db.commit()
            with patch("server.send_interview_reminder_email") as mock_send:
                sent = _s._send_due_interview_reminders()
            assert sent >= 1
            db.refresh(u)
            assert u.interview_reminder_sent is True
            mock_send.assert_called()
        finally:
            cleanup(db, u)
            db.close()

    def test_reminder_picks_up_date_today():
        import server as _s
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.paid)
            # Today's date should still be caught by the widened range check
            u.interview_date = _utc_today()
            u.interview_reminder_sent = False
            db.commit()
            with patch("server.send_interview_reminder_email") as mock_send:
                sent = _s._send_due_interview_reminders()
            assert sent >= 1
            db.refresh(u)
            assert u.interview_reminder_sent is True
        finally:
            cleanup(db, u)
            db.close()

    def test_unauthenticated_returns_401_or_redirect():
        r = client.post(
            "/api/session/feedback",
            json={"rating": 3},
            follow_redirects=False,
        )
        assert r.status_code in (401, 302, 307), r.status_code

    def test_app_page_contains_feedback_overlay_and_hidden_button():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.paid)
            u.email_verified = True
            u.setup_complete = True
            u.welcome_seen = True
            db.commit()
            r = client.get("/app", cookies={"session": _cookie(u)})
            assert r.status_code == 200, r.text
            assert 'id="feedback-overlay"' in r.text
            assert 'id="interview-done-btn"' in r.text
            assert 'style="display:none"' in r.text
        finally:
            cleanup(db, u)
            db.close()

    def test_admin_feedback_requires_auth():
        r = client.get("/admin/feedback", follow_redirects=False)
        assert r.status_code in (401, 302, 307), r.status_code

    def test_admin_feedback_renders_comment():
        db = SessionLocal()
        admin = None
        u = None
        try:
            admin, token = _make_admin_cookie(db)
            u = make_user(db, AccountLevel.paid)
            db.add(SessionFeedback(
                user_id=u.id,
                rating=5,
                comment="Absolutely nailed it",
                next_interview_date=None,
                answer_count=7,
                duration_seconds=600,
            ))
            db.commit()
            r = client.get("/admin/feedback", cookies={"session": token})
            assert r.status_code == 200, r.text
            assert "Absolutely nailed it" in r.text
        finally:
            cleanup(db, admin)
            cleanup(db, u)
            db.close()

    test("Valid feedback submit persists row",         test_valid_submit_persists_row)
    test("Rating 0 is rejected (422)",                 test_rating_zero_rejected)
    test("Rating 6 is rejected (422)",                 test_rating_six_rejected)
    test("next_interview_date sets user date + rearms",test_next_interview_date_sets_user_date_and_rearms_reminder)
    test("Same date does not re-arm sent reminder",    test_same_date_does_not_rearm_already_sent_reminder)
    test("Past date is rejected (400)",                test_past_date_rejected)
    test("Reminder loop picks up tomorrow's date",     test_reminder_picks_up_user_with_date_tomorrow)
    test("Reminder loop picks up today's date (range fix)", test_reminder_picks_up_date_today)
    test("Unauthenticated → 401/redirect",             test_unauthenticated_returns_401_or_redirect)
    test("/app contains hidden feedback overlay+button",test_app_page_contains_feedback_overlay_and_hidden_button)
    test("/admin/feedback requires auth",              test_admin_feedback_requires_auth)
    test("/admin/feedback renders submitted comment",  test_admin_feedback_renders_comment)
