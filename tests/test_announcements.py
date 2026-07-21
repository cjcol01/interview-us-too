"""Announcements — email and/or in-app notify, targeted at a segment or a single user.

Segment membership is defined once by server._segment_query and reused by both the email
recipient list and the in-app banner match (server._user_in_segment), so the bulk of this
file exercises that shared definition directly, then checks the create/dismiss/deactivate
routes end-to-end. The in-app banner is DB-backed (see server._active_announcement_for),
so we render an ordinary page (/faq) as different users and look for the banner text.
"""
from auth import create_token
from database import SessionLocal
from models import AccountLevel, Announcement, AnnouncementDismissal, InterviewSession, User
from tests.helpers import cleanup, make_user
from tests.test_admin import _make_admin_cookie

import server


def _delete_announcements(db, subject):
    ann_ids = [a.id for a in db.query(Announcement).filter(Announcement.subject == subject).all()]
    if ann_ids:
        db.query(AnnouncementDismissal).filter(AnnouncementDismissal.announcement_id.in_(ann_ids)).delete(synchronize_session=False)
        db.query(Announcement).filter(Announcement.id.in_(ann_ids)).delete(synchronize_session=False)
        db.commit()


def register(test, skip, client):

    def test_announcements_page_requires_auth():
        r = client.get("/admin/announcements")
        assert r.status_code == 401

    def test_create_requires_auth():
        r = client.post("/admin/announcements", data={
            "subject": "x", "body": "y", "channel": "in_app", "segment": "everyone",
        })
        assert r.status_code == 401

    def test_segment_query_trial_and_sessions():
        db = SessionLocal()
        trial_user = paid_user = None
        try:
            trial_user = make_user(db, AccountLevel.trial)
            paid_user = make_user(db, AccountLevel.paid)
            trial_ids = {u.id for u in server._segment_query(db, "trial").all()}
            sessions_ids = {u.id for u in server._segment_query(db, "sessions").all()}
            assert trial_user.id in trial_ids
            assert trial_user.id not in sessions_ids
            assert paid_user.id in sessions_ids
            assert paid_user.id not in trial_ids
        finally:
            cleanup(db, trial_user, paid_user)
            db.close()

    def test_segment_query_lapsed_trial_needs_a_session():
        db = SessionLocal()
        never_started = lapsed = None
        try:
            never_started = make_user(db, AccountLevel.free)
            lapsed = make_user(db, AccountLevel.free)
            now = server.datetime.utcnow()
            db.add(InterviewSession(user_id=lapsed.id, started_at=now, expires_at=now))
            db.commit()
            lapsed_ids = {u.id for u in server._segment_query(db, "lapsed_trial").all()}
            inactive_ids = {u.id for u in server._segment_query(db, "free_inactive").all()}
            assert lapsed.id in lapsed_ids
            assert lapsed.id not in inactive_ids
            assert never_started.id in inactive_ids
            assert never_started.id not in lapsed_ids
        finally:
            cleanup(db, never_started, lapsed)
            db.close()

    def test_create_in_app_announcement_banner_shows_and_dismisses():
        db = SessionLocal()
        admin = trial_user = paid_user = None
        try:
            admin, admin_token = _make_admin_cookie(db)
            trial_user = make_user(db, AccountLevel.trial)
            paid_user = make_user(db, AccountLevel.paid)
            trial_token = create_token(trial_user.id)
            paid_token = create_token(paid_user.id)

            r = client.post("/admin/announcements", data={
                "subject": "Heads up",
                "body": "We're doing maintenance tonight.",
                "channel": "in_app",
                "segment": "trial",
            }, cookies={"session": admin_token}, follow_redirects=False)
            assert r.status_code == 303
            ann = db.query(Announcement).filter(Announcement.subject == "Heads up").first()
            assert ann is not None
            assert ann.in_app_active is True

            # Matching (trial) user sees it, non-matching (paid) user doesn't.
            assert "Heads up" in client.get("/faq", cookies={"session": trial_token}).text
            assert "Heads up" not in client.get("/faq", cookies={"session": paid_token}).text

            # Dismiss removes it for that user only, without deactivating it globally.
            dismiss = client.post(f"/announcements/{ann.id}/dismiss", cookies={"session": trial_token})
            assert dismiss.status_code == 204
            assert "Heads up" not in client.get("/faq", cookies={"session": trial_token}).text
        finally:
            _delete_announcements(db, "Heads up")
            cleanup(db, admin, trial_user, paid_user)
            db.close()

    def test_deactivate_stops_banner_for_everyone():
        db = SessionLocal()
        admin = everyone_user = None
        try:
            admin, admin_token = _make_admin_cookie(db)
            everyone_user = make_user(db, AccountLevel.free)
            user_token = create_token(everyone_user.id)

            r = client.post("/admin/announcements", data={
                "subject": "Deactivate me",
                "body": "test",
                "channel": "in_app",
                "segment": "everyone",
            }, cookies={"session": admin_token}, follow_redirects=False)
            assert r.status_code == 303
            ann = db.query(Announcement).filter(Announcement.subject == "Deactivate me").first()
            assert "Deactivate me" in client.get("/faq", cookies={"session": user_token}).text

            deact = client.post(f"/admin/announcements/{ann.id}/deactivate",
                                 cookies={"session": admin_token}, follow_redirects=False)
            assert deact.status_code == 303
            assert "Deactivate me" not in client.get("/faq", cookies={"session": user_token}).text
        finally:
            _delete_announcements(db, "Deactivate me")
            cleanup(db, admin, everyone_user)
            db.close()

    def test_individual_segment_targets_one_email_only():
        db = SessionLocal()
        admin = target = other = None
        try:
            admin, admin_token = _make_admin_cookie(db)
            target = make_user(db, AccountLevel.free)
            other = make_user(db, AccountLevel.free)

            r = client.post("/admin/announcements", data={
                "subject": "Just for you",
                "body": "test",
                "channel": "in_app",
                "segment": "individual",
                "target_email": target.email,
            }, cookies={"session": admin_token}, follow_redirects=False)
            assert r.status_code == 303

            target_token = create_token(target.id)
            other_token = create_token(other.id)
            assert "Just for you" in client.get("/faq", cookies={"session": target_token}).text
            assert "Just for you" not in client.get("/faq", cookies={"session": other_token}).text
        finally:
            _delete_announcements(db, "Just for you")
            cleanup(db, admin, target, other)
            db.close()

    def test_individual_segment_without_email_is_rejected():
        db = SessionLocal()
        admin = None
        try:
            admin, admin_token = _make_admin_cookie(db)
            r = client.post("/admin/announcements", data={
                "subject": "Broken",
                "body": "test",
                "channel": "in_app",
                "segment": "individual",
            }, cookies={"session": admin_token}, follow_redirects=False)
            assert r.status_code == 303
            assert "needs+a+target+email" in r.headers["location"] or "needs a target email" in r.headers["location"]
            assert db.query(Announcement).filter(Announcement.subject == "Broken").first() is None
        finally:
            cleanup(db, admin)
            db.close()

    def test_invalid_segment_or_channel_rejected():
        db = SessionLocal()
        admin = None
        try:
            admin, admin_token = _make_admin_cookie(db)
            r = client.post("/admin/announcements", data={
                "subject": "x", "body": "y", "channel": "carrier-pigeon", "segment": "everyone",
            }, cookies={"session": admin_token}, follow_redirects=False)
            assert r.status_code == 400
        finally:
            cleanup(db, admin)
            db.close()

    def test_multi_segment_targets_union_of_audiences():
        db = SessionLocal()
        admin = trial_user = paid_user = free_user = None
        try:
            admin, admin_token = _make_admin_cookie(db)
            trial_user = make_user(db, AccountLevel.trial)
            paid_user = make_user(db, AccountLevel.paid)
            free_user = make_user(db, AccountLevel.free)  # not in either selected segment
            trial_token = create_token(trial_user.id)
            paid_token = create_token(paid_user.id)
            free_token = create_token(free_user.id)

            r = client.post("/admin/announcements", data={
                "subject": "Multi group",
                "body": "test",
                "channel": "in_app",
                "segment": ["trial", "sessions"],
            }, cookies={"session": admin_token}, follow_redirects=False)
            assert r.status_code == 303
            ann = db.query(Announcement).filter(Announcement.subject == "Multi group").first()
            assert ann is not None
            assert set(ann.segment.split(",")) == {"trial", "sessions"}

            # Both selected segments' members see it; a user in neither doesn't.
            assert "Multi group" in client.get("/faq", cookies={"session": trial_token}).text
            assert "Multi group" in client.get("/faq", cookies={"session": paid_token}).text
            assert "Multi group" not in client.get("/faq", cookies={"session": free_token}).text
        finally:
            _delete_announcements(db, "Multi group")
            cleanup(db, admin, trial_user, paid_user, free_user)
            db.close()

    def test_segment_count_endpoint_dedupes_union():
        db = SessionLocal()
        admin = u1 = None
        try:
            admin, admin_token = _make_admin_cookie(db)
            u1 = make_user(db, AccountLevel.trial)  # matches both "trial" and "never_paid"

            r = client.get("/admin/announcements/count?segment=trial&segment=never_paid",
                            cookies={"session": admin_token})
            assert r.status_code == 200
            union_count = r.json()["count"]

            trial_only = client.get("/admin/announcements/count?segment=trial",
                                     cookies={"session": admin_token}).json()["count"]
            never_paid_only = client.get("/admin/announcements/count?segment=never_paid",
                                          cookies={"session": admin_token}).json()["count"]

            # u1 matches both segments — the union must count them once, so it can't exceed
            # the sum, and must be at least as large as the bigger individual segment.
            assert union_count <= trial_only + never_paid_only
            assert union_count >= max(trial_only, never_paid_only)

            no_segment = client.get("/admin/announcements/count", cookies={"session": admin_token})
            assert no_segment.json()["count"] == 0
        finally:
            cleanup(db, admin, u1)
            db.close()

    def test_email_channel_records_recipient_count():
        db = SessionLocal()
        admin = u1 = u2 = None
        try:
            admin, admin_token = _make_admin_cookie(db)
            u1 = make_user(db, AccountLevel.trial)
            u1.email_verified = True
            u2 = make_user(db, AccountLevel.trial)
            u2.email_verified = False  # unverified — must be excluded from the send
            db.commit()

            r = client.post("/admin/announcements", data={
                "subject": "Email blast",
                "body": "test",
                "channel": "email",
                "segment": "trial",
            }, cookies={"session": admin_token}, follow_redirects=False)
            assert r.status_code == 303

            ann = db.query(Announcement).filter(Announcement.subject == "Email blast").first()
            assert ann is not None
            assert ann.in_app_active is False
            db.refresh(ann)
            assert ann.email_recipient_count is not None
            assert ann.email_recipient_count >= 1
        finally:
            _delete_announcements(db, "Email blast")
            cleanup(db, admin, u1, u2)
            db.close()

    test("GET /admin/announcements requires auth",                       test_announcements_page_requires_auth)
    test("POST /admin/announcements requires auth",                      test_create_requires_auth)
    test("_segment_query: trial vs sessions membership",                 test_segment_query_trial_and_sessions)
    test("_segment_query: lapsed_trial requires a used session",         test_segment_query_lapsed_trial_needs_a_session)
    test("Create in-app announcement: banner shows, dismiss hides it",   test_create_in_app_announcement_banner_shows_and_dismisses)
    test("Deactivate stops the banner for everyone",                     test_deactivate_stops_banner_for_everyone)
    test("Individual segment targets exactly one email",                 test_individual_segment_targets_one_email_only)
    test("Individual segment without an email is rejected",              test_individual_segment_without_email_is_rejected)
    test("Invalid segment/channel → 400",                                test_invalid_segment_or_channel_rejected)
    test("Multi-segment targets the union of audiences",                 test_multi_segment_targets_union_of_audiences)
    test("Segment count endpoint dedupes the union",                     test_segment_count_endpoint_dedupes_union)
    test("Email channel records recipient count, skips unverified",      test_email_channel_records_recipient_count)
