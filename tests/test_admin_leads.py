import csv
import io
from datetime import datetime, timedelta

from tests.test_admin import _make_admin_cookie


def register(test, skip, client):
    from database import SessionLocal
    from models import AccountLevel, User
    from tests.helpers import cleanup, delete_leads, make_lead, make_user

    def test_requires_auth():
        r1 = client.get("/admin/leads", follow_redirects=False)
        r2 = client.get("/admin/leads/export.csv", follow_redirects=False)
        assert r1.status_code == 401
        assert r2.status_code == 401

    def test_lists_unclaimed_and_claimed_leads():
        db = SessionLocal()
        admin = u = lead1 = lead2 = None
        try:
            admin, token = _make_admin_cookie(db)
            u = make_user(db, AccountLevel.trial)
            lead1 = make_lead(db)
            lead2 = make_lead(db, claimed=True, user=u)

            r = client.get("/admin/leads", cookies={"session": token})
            assert r.status_code == 200
            assert lead1.email in r.text
            assert lead2.email in r.text
            assert u.account_level.value in r.text  # the "Account" column shows the level, linking through
        finally:
            delete_leads(db, lead1.email if lead1 else None, lead2.email if lead2 else None)
            cleanup(db, u, admin)
            db.close()

    def test_search_matches_unclaimed_lead_on_its_own_email():
        """The outer-join trap: a bare User.email predicate on an outer join would silently
        drop every unjoined (unclaimed) row. This proves the OR across both sides works."""
        db = SessionLocal()
        admin = lead = None
        try:
            admin, token = _make_admin_cookie(db)
            lead = make_lead(db)
            r = client.get(f"/admin/leads?q={lead.email}", cookies={"session": token})
            assert lead.email in r.text
        finally:
            delete_leads(db, lead.email if lead else None)
            cleanup(db, admin)
            db.close()

    def test_search_matches_claimed_lead_on_linked_account_email():
        db = SessionLocal()
        admin = u = lead = None
        try:
            admin, token = _make_admin_cookie(db)
            u = make_user(db, AccountLevel.trial)
            lead = make_lead(db, claimed=True, user=u)
            r = client.get(f"/admin/leads?q={u.email}", cookies={"session": token})
            assert lead.email in r.text
        finally:
            delete_leads(db, lead.email if lead else None)
            cleanup(db, u, admin)
            db.close()

    def test_status_filter_unclaimed_vs_claimed():
        db = SessionLocal()
        admin = u = lead_unclaimed = lead_claimed = None
        try:
            admin, token = _make_admin_cookie(db)
            u = make_user(db, AccountLevel.trial)
            lead_unclaimed = make_lead(db)
            lead_claimed = make_lead(db, claimed=True, user=u)

            r1 = client.get("/admin/leads?status=unclaimed", cookies={"session": token})
            assert lead_unclaimed.email in r1.text
            assert lead_claimed.email not in r1.text

            r2 = client.get("/admin/leads?status=claimed", cookies={"session": token})
            assert lead_claimed.email in r2.text
            assert lead_unclaimed.email not in r2.text
        finally:
            delete_leads(db, lead_unclaimed.email if lead_unclaimed else None, lead_claimed.email if lead_claimed else None)
            cleanup(db, u, admin)
            db.close()

    def test_status_filter_unfinished():
        db = SessionLocal()
        admin = u_unfinished = u_finished = lead_a = lead_b = None
        try:
            admin, token = _make_admin_cookie(db)
            u_unfinished = make_user(db, AccountLevel.trial)
            u_unfinished.password_set = False
            u_finished = make_user(db, AccountLevel.trial)
            u_finished.password_set = True
            db.commit()
            lead_a = make_lead(db, claimed=True, user=u_unfinished)
            lead_b = make_lead(db, claimed=True, user=u_finished)

            r = client.get("/admin/leads?status=unfinished", cookies={"session": token})
            assert lead_a.email in r.text
            assert lead_b.email not in r.text
        finally:
            delete_leads(db, lead_a.email if lead_a else None, lead_b.email if lead_b else None)
            cleanup(db, u_unfinished, u_finished, admin)
            db.close()

    def test_unknown_status_falls_back_to_all():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin/leads?status=nonsense", cookies={"session": token})
            assert r.status_code == 200
        finally:
            cleanup(db, admin)
            db.close()

    def test_csv_export_shape_and_content():
        db = SessionLocal()
        admin = lead = None
        try:
            admin, token = _make_admin_cookie(db)
            lead = make_lead(db, attribution='{"utm_source":"google","gclid":"abc123"}')

            r = client.get("/admin/leads/export.csv", cookies={"session": token})
            assert r.status_code == 200
            assert "attachment" in r.headers.get("content-disposition", "")
            assert "interview-wise-leads-" in r.headers.get("content-disposition", "")

            rows = list(csv.reader(io.StringIO(r.text)))
            header = rows[0]
            assert header == [
                "email", "captured_at", "kind", "request_count", "claimed_at", "claim_count",
                "gclid", "fbclid", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                "referer", "ref_code", "interview_date",
                "user_email", "account_level", "password_set", "setup_complete", "ever_paid",
            ]
            data_rows = {row[0]: row for row in rows[1:]}
            assert lead.email in data_rows
            row = data_rows[lead.email]
            assert row[header.index("gclid")] == "abc123"
            assert row[header.index("utm_source")] == "google"
        finally:
            delete_leads(db, lead.email if lead else None)
            cleanup(db, admin)
            db.close()

    def test_csv_honours_status_filter():
        db = SessionLocal()
        admin = u = lead_unclaimed = lead_claimed = None
        try:
            admin, token = _make_admin_cookie(db)
            u = make_user(db, AccountLevel.trial)
            lead_unclaimed = make_lead(db)
            lead_claimed = make_lead(db, claimed=True, user=u)

            r = client.get("/admin/leads/export.csv?status=unclaimed", cookies={"session": token})
            assert lead_unclaimed.email in r.text
            assert lead_claimed.email not in r.text
        finally:
            delete_leads(db, lead_unclaimed.email if lead_unclaimed else None, lead_claimed.email if lead_claimed else None)
            cleanup(db, u, admin)
            db.close()

    def test_csv_never_contains_lead_ip():
        db = SessionLocal()
        admin = lead = None
        try:
            admin, token = _make_admin_cookie(db)
            lead = make_lead(db)
            lead.ip = "203.0.113.99"
            db.commit()

            r = client.get("/admin/leads/export.csv", cookies={"session": token})
            assert "203.0.113.99" not in r.text
        finally:
            delete_leads(db, lead.email if lead else None)
            cleanup(db, admin)
            db.close()

    def test_csv_empty_result_still_has_header():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin/leads/export.csv?q=_nonexistent_needle_xyz", cookies={"session": token})
            rows = list(csv.reader(io.StringIO(r.text)))
            assert len(rows) == 1
            assert rows[0][0] == "email"
        finally:
            cleanup(db, admin)
            db.close()

    test("GET /admin/leads and export.csv require auth",                test_requires_auth)
    test("GET /admin/leads lists unclaimed and claimed leads",           test_lists_unclaimed_and_claimed_leads)
    test("GET /admin/leads: search matches unclaimed lead's own email",  test_search_matches_unclaimed_lead_on_its_own_email)
    test("GET /admin/leads: search matches claimed lead's account email", test_search_matches_claimed_lead_on_linked_account_email)
    test("GET /admin/leads: status=unclaimed/claimed filter correctly", test_status_filter_unclaimed_vs_claimed)
    test("GET /admin/leads: status=unfinished filters on password_set", test_status_filter_unfinished)
    test("GET /admin/leads: unknown status falls back to all",          test_unknown_status_falls_back_to_all)
    test("GET /admin/leads/export.csv: header + content shape",         test_csv_export_shape_and_content)
    test("GET /admin/leads/export.csv: honours status filter",          test_csv_honours_status_filter)
    test("GET /admin/leads/export.csv: never contains Lead.ip",         test_csv_never_contains_lead_ip)
    test("GET /admin/leads/export.csv: empty result still has header",  test_csv_empty_result_still_has_header)
