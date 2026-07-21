"""Growth dashboard (`GET /admin/dashboard`) — gated by _require_author, pure DB aggregates
over existing tables. Other test modules seed/clean up their own users against the same
database within a single suite run, so we assert wiring + relative deltas rather than exact
global counts.
"""
from database import SessionLocal
from models import AccountLevel
from tests.helpers import cleanup, make_user
from tests.test_admin import _make_admin_cookie


def register(test, skip, client):

    def test_dashboard_requires_auth():
        r = client.get("/admin/dashboard")
        assert r.status_code == 401

    def test_dashboard_success_renders():
        db = SessionLocal()
        admin = target = None
        try:
            admin, token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.unlimited)
            target.stripe_sub_id = "sub_test_dashboard"
            db.commit()

            r = client.get("/admin/dashboard", cookies={"session": token})
            assert r.status_code == 200
            assert "Growth dashboard" in r.text
            assert "MRR" in r.text
        finally:
            cleanup(db, admin, target)
            db.close()

    def test_dashboard_drilldown_shows_matching_user_only():
        db = SessionLocal()
        admin = trial_user = paid_user = None
        try:
            admin, token = _make_admin_cookie(db)
            trial_user = make_user(db, AccountLevel.trial)
            paid_user = make_user(db, AccountLevel.paid)

            r = client.get("/admin/dashboard?segment=level_trial", cookies={"session": token})
            assert r.status_code == 200
            assert trial_user.email in r.text
            assert paid_user.email not in r.text
            assert 'ua-search' in r.text  # search box present in the drill-down
        finally:
            cleanup(db, admin, trial_user, paid_user)
            db.close()

    def test_dashboard_drilldown_search_filters_within_segment():
        db = SessionLocal()
        admin = trial_a = trial_b = None
        try:
            admin, token = _make_admin_cookie(db)
            trial_a = make_user(db, AccountLevel.trial)
            trial_b = make_user(db, AccountLevel.trial)

            r = client.get(f"/admin/dashboard?segment=level_trial&q={trial_a.username}", cookies={"session": token})
            assert trial_a.email in r.text
            assert trial_b.email not in r.text
        finally:
            cleanup(db, admin, trial_a, trial_b)
            db.close()

    def test_dashboard_invalid_segment_is_ignored():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin/dashboard?segment=not-a-real-segment", cookies={"session": token})
            assert r.status_code == 200
            # The side panel itself is always rendered (fixed layout — see admin.css) but
            # falls back to the idle placeholder rather than a real drilldown for a bad key.
            assert "Click a card on the left" in r.text
        finally:
            cleanup(db, admin)
            db.close()

    test("GET /admin/dashboard requires auth",   test_dashboard_requires_auth)
    test("GET /admin/dashboard: success renders", test_dashboard_success_renders)
    test("GET /admin/dashboard?segment=X: shows only matching users", test_dashboard_drilldown_shows_matching_user_only)
    test("GET /admin/dashboard?segment=X&q=: search filters within segment", test_dashboard_drilldown_search_filters_within_segment)
    test("GET /admin/dashboard?segment=invalid: ignored, no drilldown", test_dashboard_invalid_segment_is_ignored)
