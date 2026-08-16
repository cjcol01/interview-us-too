"""Admin user-management routes: ban/unban/pause-subscription/resume-subscription/warn.

All five routes are gated by `_require_author`, which accepts either HTTP Basic auth
(needs AUTHOR_PASSWORD, usually unset locally/in tests) or a session cookie belonging to
the account named by ADMIN_USERNAME — we use the latter to exercise the success paths.
run_tests.py pins that env var to a test-only value, so this never depends on the real one.
"""
import secrets as _sec
from unittest.mock import patch

import stripe

from config import ADMIN_USERNAME
from auth import create_token, hash_password
from database import SessionLocal
from models import AccountLevel, User
from tests.helpers import cleanup, delete_by_name, make_user


class _FakeStripeObj(dict):
    def to_dict(self):
        return dict(self)


def _make_admin_cookie(db):
    # Purge any stale row from a previous crashed test run before inserting.
    # UniqueViolation on the username index would otherwise poison the session
    # and cascade failures through every subsequent admin test.
    stale = db.query(User).filter(User.username == ADMIN_USERNAME).first()
    if stale:
        db.delete(stale)
        db.commit()

    admin = User(
        username=ADMIN_USERNAME,
        email=f"_test_admin_{_sec.token_hex(4)}@test.internal",
        full_name="Admin",
        password_hash=hash_password("adminpass123"),
        account_level=AccountLevel.unlimited,
        api_token=_sec.token_urlsafe(32),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin, create_token(admin.id)


def register(test, skip, client):

    def test_ban_requires_auth():
        r = client.post("/admin/users/1/ban", follow_redirects=False)
        assert r.status_code == 401

    def test_ban_unknown_user_404():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            r = client.post("/admin/users/999999999/ban",
                            cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 404
        finally:
            cleanup(db, admin)
            db.close()

    def test_ban_success_deactivates_user():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.trial)
            r = client.post(f"/admin/users/{target.id}/ban",
                            cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            assert r.headers["location"].startswith("/admin/usage")
            db.refresh(target)
            assert target.is_active is False
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_unban_success_reactivates_user():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.trial)
            target.is_active = False
            db.commit()
            r = client.post(f"/admin/users/{target.id}/unban",
                            cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            db.refresh(target)
            assert target.is_active is True
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_pause_subscription_no_sub_shows_message():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.unlimited)  # no stripe_sub_id set
            r = client.post(f"/admin/users/{target.id}/pause-subscription",
                            cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            assert "no+active+subscription" in r.headers["location"] or "no active subscription" in r.headers["location"]
            db.refresh(target)
            assert target.account_level == AccountLevel.unlimited  # unchanged
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_pause_subscription_stripe_error_handled():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.unlimited, stripe_id=f"cus_test_{_sec.token_hex(6)}")
            target.stripe_sub_id = f"sub_test_{_sec.token_hex(6)}"
            db.commit()
            with patch("billing.stripe.Subscription.modify",
                       side_effect=stripe.error.StripeError("boom")):
                r = client.post(f"/admin/users/{target.id}/pause-subscription",
                                cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            assert "Stripe+error" in r.headers["location"] or "Stripe error" in r.headers["location"]
            db.refresh(target)
            assert target.account_level == AccountLevel.unlimited  # unchanged — pause never committed
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_pause_subscription_success():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.unlimited, stripe_id=f"cus_test_{_sec.token_hex(6)}")
            target.stripe_sub_id = f"sub_test_{_sec.token_hex(6)}"
            db.commit()
            with patch("billing.stripe.Subscription.modify", return_value=None):
                r = client.post(f"/admin/users/{target.id}/pause-subscription",
                                cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            db.refresh(target)
            assert target.account_level == AccountLevel.free
            assert target.account_flag == "paused"
            assert target.account_flag_seen is False
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_resume_subscription_no_sub_shows_message():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.free)  # no stripe_sub_id set
            r = client.post(f"/admin/users/{target.id}/resume-subscription",
                            cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            assert "no+active+subscription" in r.headers["location"] or "no active subscription" in r.headers["location"]
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_resume_subscription_stripe_error_handled():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.free, stripe_id=f"cus_test_{_sec.token_hex(6)}")
            target.stripe_sub_id = f"sub_test_{_sec.token_hex(6)}"
            target.account_flag = "paused"
            db.commit()
            with patch("billing.stripe.Subscription.modify",
                       side_effect=stripe.error.StripeError("boom")):
                r = client.post(f"/admin/users/{target.id}/resume-subscription",
                                cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            db.refresh(target)
            assert target.account_flag == "paused"  # unchanged — resume never committed
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_resume_subscription_success():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            cid = f"cus_test_{_sec.token_hex(6)}"
            sid = f"sub_test_{_sec.token_hex(6)}"
            target = make_user(db, AccountLevel.free, stripe_id=cid)
            target.stripe_sub_id = sid
            target.account_flag = "paused"
            db.commit()
            fake_sub = _FakeStripeObj({
                "id": sid, "customer": cid, "status": "active",
                "cancel_at_period_end": False, "cancel_at": None, "trial_end": None,
            })
            with patch("billing.stripe.Subscription.modify", return_value=None), \
                 patch("billing.stripe.Subscription.retrieve", return_value=fake_sub):
                r = client.post(f"/admin/users/{target.id}/resume-subscription",
                                cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            db.refresh(target)
            assert target.account_flag == "resumed"
            assert target.account_flag_seen is False
            assert target.account_level == AccountLevel.unlimited  # resynced via _sync_subscription
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_warn_user_success():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.trial)
            r = client.post(f"/admin/users/{target.id}/warn",
                            cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            assert "Warning+emailed" in r.headers["location"] or "Warning emailed" in r.headers["location"]
        finally:
            cleanup(db, admin, target)
            db.close()

    test("POST /admin/users/{id}/ban requires auth",                    test_ban_requires_auth)
    test("POST /admin/users/{id}/ban: unknown user → 404",              test_ban_unknown_user_404)
    test("POST /admin/users/{id}/ban: success deactivates user",        test_ban_success_deactivates_user)
    test("POST /admin/users/{id}/unban: success reactivates user",      test_unban_success_reactivates_user)
    test("POST pause-subscription: no sub → message, unchanged",        test_pause_subscription_no_sub_shows_message)
    test("POST pause-subscription: Stripe error handled",                test_pause_subscription_stripe_error_handled)
    test("POST pause-subscription: success sets free+paused",           test_pause_subscription_success)
    test("POST resume-subscription: no sub → message",                  test_resume_subscription_no_sub_shows_message)
    test("POST resume-subscription: Stripe error handled",               test_resume_subscription_stripe_error_handled)
    test("POST resume-subscription: success resyncs account",           test_resume_subscription_success)
    def test_expiry_reminder_no_cancellation_shows_message():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.unlimited)
            r = client.post(f"/admin/users/{target.id}/send-expiry-reminder",
                            cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            assert "no+scheduled+cancellation" in r.headers["location"] or "no scheduled cancellation" in r.headers["location"]
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_expiry_reminder_success():
        from datetime import datetime, timedelta
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.unlimited)
            target.sub_cancel_at = datetime.utcnow() + timedelta(days=5)
            db.commit()
            r = client.post(f"/admin/users/{target.id}/send-expiry-reminder",
                            cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            assert "reminder+emailed" in r.headers["location"] or "reminder emailed" in r.headers["location"]
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_low_sessions_success():
        db = SessionLocal()
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.paid)
            r = client.post(f"/admin/users/{target.id}/send-low-sessions",
                            cookies={"session": token}, follow_redirects=False)
            assert r.status_code == 303
            assert "notice+emailed" in r.headers["location"] or "notice emailed" in r.headers["location"]
        finally:
            cleanup(db, admin, target)
            db.close()

    test("POST /admin/users/{id}/warn: success emails+redirects",       test_warn_user_success)
    test("POST send-expiry-reminder: no cancellation → message",        test_expiry_reminder_no_cancellation_shows_message)
    test("POST send-expiry-reminder: success emails+redirects",         test_expiry_reminder_success)
    test("POST send-low-sessions: success emails+redirects",            test_low_sessions_success)
