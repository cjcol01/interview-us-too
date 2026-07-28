"""Growth dashboard (`GET /admin/dashboard`) — gated by _require_author, pure DB aggregates
over existing tables. Other test modules seed/clean up their own users against the same
database within a single suite run, so we assert wiring + relative deltas rather than exact
global counts.
"""
from database import SessionLocal
from models import AccountLevel
from tests.helpers import cleanup, delete_leads, make_lead, make_user
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

    def test_dashboard_lead_unfinished_segment():
        db = SessionLocal()
        admin = unfinished = normal_trial = None
        try:
            admin, token = _make_admin_cookie(db)
            unfinished = make_user(db, AccountLevel.trial)
            unfinished.password_set = False
            normal_trial = make_user(db, AccountLevel.trial)
            db.commit()

            r = client.get("/admin/dashboard?segment=lead_unfinished", cookies={"session": token})
            assert r.status_code == 200
            assert unfinished.email in r.text
            assert normal_trial.email not in r.text
        finally:
            cleanup(db, admin, unfinished, normal_trial)
            db.close()

    def test_dashboard_lead_trial_segment_requires_linked_lead():
        """Proves the EXISTS join is doing work: an identical trial user with no Lead row
        must be excluded, since password_set/account_level alone can't distinguish origin
        once password_set has flipped True."""
        db = SessionLocal()
        admin = with_lead = without_lead = lead = None
        try:
            admin, token = _make_admin_cookie(db)
            with_lead = make_user(db, AccountLevel.trial)
            without_lead = make_user(db, AccountLevel.trial)
            lead = make_lead(db, claimed=True, user=with_lead)

            r = client.get("/admin/dashboard?segment=lead_trial", cookies={"session": token})
            assert with_lead.email in r.text
            assert without_lead.email not in r.text
        finally:
            delete_leads(db, lead.email if lead else None)
            cleanup(db, admin, with_lead, without_lead)
            db.close()

    def test_dashboard_attribution_survives_malformed_json():
        """Regression test for the _attribution_json truncation bug: without the
        json_valid() guard, a single malformed Lead.attribution row makes json_extract raise
        and the whole dashboard 500s."""
        db = SessionLocal()
        admin = lead = None
        try:
            admin, token = _make_admin_cookie(db)
            lead = make_lead(db, attribution='{"utm_source":"goog')  # deliberately truncated/invalid
            r = client.get("/admin/dashboard", cookies={"session": token})
            assert r.status_code == 200
            assert "Ad attribution" in r.text
        finally:
            delete_leads(db, lead.email if lead else None)
            cleanup(db, admin)
            db.close()

    def test_dashboard_attribution_buckets_by_source():
        db = SessionLocal()
        admin = lead_google = lead_meta = lead_direct = None
        try:
            admin, token = _make_admin_cookie(db)
            lead_google = make_lead(db, attribution='{"utm_source":"google"}')
            lead_meta = make_lead(db, attribution='{"utm_source":"meta"}')
            lead_direct = make_lead(db, attribution=None)

            r = client.get("/admin/dashboard", cookies={"session": token})
            assert ">google<" in r.text or "google" in r.text
            assert "meta" in r.text
            assert "direct" in r.text
        finally:
            delete_leads(db, lead_google.email if lead_google else None,
                         lead_meta.email if lead_meta else None,
                         lead_direct.email if lead_direct else None)
            cleanup(db, admin)
            db.close()

    def test_dashboard_funnel_renders():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin/dashboard", cookies={"session": token})
            assert "Mobile lead funnel" in r.text
            assert "ad-funnel-bar" in r.text
        finally:
            cleanup(db, admin)
            db.close()

    def _funnel_stage_count(html, label):
        import re
        m = re.search(re.escape(label) + r'</div>\s*<div class="ad-funnel-track">.*?<div class="ad-funnel-value">(\d+)', html, re.S)
        return int(m.group(1)) if m else None

    def test_dashboard_funnel_excludes_existing_kind_leads():
        db = SessionLocal()
        admin = u = lead_existing = None
        try:
            admin, token = _make_admin_cookie(db)
            u = make_user(db, AccountLevel.unlimited)
            u.intro_redeemed = True
            db.commit()

            r_before = client.get("/admin/dashboard", cookies={"session": token})
            paid_before = _funnel_stage_count(r_before.text, "Paid")
            assert paid_before is not None

            lead_existing = make_lead(db, kind="existing", claimed=True, user=u)

            r_after = client.get("/admin/dashboard", cookies={"session": token})
            paid_after = _funnel_stage_count(r_after.text, "Paid")
            # The new lead is claimed, linked to a paid user — if it counted, "Paid" would
            # go up by one. It's kind=="existing" (a login handoff, not an ad conversion),
            # so the funnel must not move at all.
            assert paid_after == paid_before
        finally:
            delete_leads(db, lead_existing.email if lead_existing else None)
            cleanup(db, admin, u)
            db.close()

    test("GET /admin/dashboard requires auth",   test_dashboard_requires_auth)
    test("GET /admin/dashboard: success renders", test_dashboard_success_renders)
    test("GET /admin/dashboard?segment=X: shows only matching users", test_dashboard_drilldown_shows_matching_user_only)
    test("GET /admin/dashboard?segment=X&q=: search filters within segment", test_dashboard_drilldown_search_filters_within_segment)
    test("GET /admin/dashboard?segment=invalid: ignored, no drilldown", test_dashboard_invalid_segment_is_ignored)
    test("GET /admin/dashboard?segment=lead_unfinished lists the right user", test_dashboard_lead_unfinished_segment)
    test("GET /admin/dashboard?segment=lead_trial requires a linked Lead", test_dashboard_lead_trial_segment_requires_linked_lead)
    test("Dashboard survives a malformed Lead.attribution row",  test_dashboard_attribution_survives_malformed_json)
    test("Dashboard attribution buckets leads by utm_source",    test_dashboard_attribution_buckets_by_source)
    test("Dashboard renders the mobile lead funnel",             test_dashboard_funnel_renders)
    test("Dashboard funnel excludes kind=='existing' leads",     test_dashboard_funnel_excludes_existing_kind_leads)
