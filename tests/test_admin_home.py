"""Admin home (`GET /admin`) — a hub linking to the other admin pages, with an alerts strip
that only lists what's actually notable (banned users, flagged referrers, low disk, etc.).
Gated by _require_author like the rest of the admin surface.

The "no alerts" case is inherently environment-dependent (AUTHOR_PASSWORD/RESEND_API_KEY
etc. may or may not be set locally — see CLAUDE.md), so that test mocks the cheap health/
config checks to a known-clean state rather than asserting on whatever this machine's .env
happens to contain.
"""
from unittest.mock import AsyncMock, patch

from database import SessionLocal
from models import AccountLevel
from tests.helpers import cleanup, make_user
from tests.test_admin import _make_admin_cookie

_OK_CHECK = {"ok": True, "detail": "stub", "latency_ms": 1.0}


def register(test, skip, client):

    def test_admin_home_requires_auth():
        r = client.get("/admin")
        assert r.status_code == 401

    def test_admin_home_success_renders_nav_and_alerts():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin", cookies={"session": token})
            assert r.status_code == 200
            assert "Growth dashboard" in r.text
            assert "System health" in r.text
            assert "Announcements" in r.text
            assert "User lookup" in r.text
            assert "API usage" in r.text
            assert "Referrals" in r.text
            assert "Partners" in r.text
            assert "Author page" in r.text
        finally:
            cleanup(db, admin)
            db.close()

    def test_admin_home_shows_no_alerts_when_clean():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            all_configured = [{"name": "X", "configured": True}]
            with patch("server._check_redis", new=AsyncMock(return_value=_OK_CHECK)), \
                 patch("server._check_database", return_value=_OK_CHECK), \
                 patch("server._check_disk", return_value=_OK_CHECK), \
                 patch("server._last_webhook_status", new=AsyncMock(return_value=_OK_CHECK)), \
                 patch("server._config_status", return_value=all_configured):
                r = client.get("/admin", cookies={"session": token})
            assert "All clear" in r.text
        finally:
            cleanup(db, admin)
            db.close()

    def test_admin_home_alerts_banned_user():
        db = SessionLocal()
        admin = banned = None
        try:
            admin, token = _make_admin_cookie(db)
            banned = make_user(db, AccountLevel.free)
            banned.is_active = False
            db.commit()

            r = client.get("/admin", cookies={"session": token})
            assert "currently banned" in r.text
            assert "/admin/dashboard?segment=banned" in r.text
        finally:
            cleanup(db, admin, banned)
            db.close()

    def test_admin_home_alerts_pending_cancellation():
        db = SessionLocal()
        admin = target = None
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.unlimited)
            from datetime import datetime, timedelta
            target.sub_cancel_at = datetime.utcnow() + timedelta(days=10)
            db.commit()

            r = client.get("/admin", cookies={"session": token})
            assert "cancel at period end" in r.text
            assert "/admin/dashboard?segment=pending_cancellations" in r.text
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_admin_home_alerts_unhealthy_redis():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            bad = {"ok": False, "detail": "boom", "latency_ms": None}
            with patch("server._check_redis", new=AsyncMock(return_value=bad)):
                r = client.get("/admin", cookies={"session": token})
            assert "Redis unreachable" in r.text
            assert "/admin/health" in r.text
        finally:
            cleanup(db, admin)
            db.close()

    test("GET /admin requires auth",                    test_admin_home_requires_auth)
    test("GET /admin: renders all nav cards",            test_admin_home_success_renders_nav_and_alerts)
    test("GET /admin: no alerts when nothing notable",   test_admin_home_shows_no_alerts_when_clean)
    test("GET /admin: alerts on a banned user",          test_admin_home_alerts_banned_user)
    test("GET /admin: alerts on a pending cancellation", test_admin_home_alerts_pending_cancellation)
    test("GET /admin: alerts on unhealthy Redis",        test_admin_home_alerts_unhealthy_redis)
