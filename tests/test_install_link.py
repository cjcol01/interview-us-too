def register(test, skip, client):
    import hashlib
    from datetime import datetime, timedelta
    from unittest.mock import patch

    from auth import create_token
    from database import SessionLocal
    from models import AccountLevel, Lead, Referral, User
    from tests.helpers import cleanup, delete_lead, make_user

    def _hash(raw):
        return hashlib.sha256(raw.encode()).hexdigest()

    # ---------------------------------------------------------------------
    # _rotate_lead_token — extracted from /api/install-link's _issue() closure so the admin
    # bulk lead-announcement sender (tests/test_announcements.py) can share it. This section
    # is the acceptance bar for that refactor: every existing test below it must keep passing
    # unedited, and these three directly pin the extracted function's contract.
    # ---------------------------------------------------------------------

    import server as _srv

    def test_rotate_lead_token_on_unclaimed_lead():
        email = "_rotate_unclaimed@test.internal"
        db = SessionLocal()
        try:
            lead = Lead(email=email, token_hash=_hash("old"), kind="new",
                        expires_at=datetime.utcnow() + timedelta(days=1),
                        ip="203.0.113.1", ref_code="REF1", attribution='{"utm_source":"google"}',
                        interview_date=None, request_count=1)
            db.add(lead)
            db.commit()

            raw = _srv._rotate_lead_token(db, lead)
            db.commit()

            assert lead.token_hash == _hash(raw)
            assert lead.token_hash != _hash("old")
            assert lead.request_count == 2
            assert lead.kind == "new"
            assert lead.expires_at > datetime.utcnow() + timedelta(days=13)
            assert lead.expires_at < datetime.utcnow() + timedelta(days=15)
            assert lead.claimed_at is None
            assert lead.claim_count == 0
            # Not first-touch capture — a bulk admin resend isn't a landing-page submission.
            assert lead.ip == "203.0.113.1"
            assert lead.ref_code == "REF1"
            assert lead.attribution == '{"utm_source":"google"}'
        finally:
            delete_lead(email)
            db.close()

    def test_rotate_lead_token_on_lead_with_existing_account():
        db = SessionLocal()
        u = None
        email = "_rotate_existing@test.internal"
        try:
            u = make_user(db, AccountLevel.trial)
            lead = Lead(email=u.email, token_hash=_hash("old"), kind="new",
                        expires_at=datetime.utcnow() + timedelta(days=1))
            db.add(lead)
            db.commit()

            raw = _srv._rotate_lead_token(db, lead)
            db.commit()

            assert lead.kind == "existing"
            assert lead.user_id == u.id
            assert lead.expires_at > datetime.utcnow() + timedelta(minutes=14)
            assert lead.expires_at < datetime.utcnow() + timedelta(minutes=16)
            delete_lead(lead.email)
        finally:
            if u:
                cleanup(db, u)
            db.close()

    def test_rotate_lead_token_clears_claim_bookkeeping():
        email = "_rotate_claim_reset@test.internal"
        db = SessionLocal()
        try:
            lead = Lead(email=email, token_hash=_hash("old"), kind="new",
                        expires_at=datetime.utcnow() + timedelta(days=1),
                        claimed_at=datetime.utcnow(), claim_count=3)
            db.add(lead)
            db.commit()

            _srv._rotate_lead_token(db, lead)
            db.commit()

            assert lead.claimed_at is None
            assert lead.claim_count == 0
        finally:
            delete_lead(email)
            db.close()

    # ---------------------------------------------------------------------
    # POST /api/install-link
    # ---------------------------------------------------------------------

    def test_install_link_new_email_creates_lead():
        email = "_lead_new1@test.internal"
        try:
            with patch("server.send_install_link_email") as sent, \
                 patch("server.send_desktop_login_email") as sent_existing:
                r = client.post("/api/install-link", json={"email": email})
                assert r.status_code == 200
                assert r.json() == {"status": "ok"}
                sent.assert_called_once()
                sent_existing.assert_not_called()
                called_email, called_token = sent.call_args[0]
                assert called_email == email

            db = SessionLocal()
            try:
                lead = db.query(Lead).filter(Lead.email == email).first()
                assert lead is not None
                assert lead.kind == "new"
                assert lead.token_hash == _hash(called_token)
                assert lead.token_hash != called_token  # stored hashed, not raw
                assert lead.expires_at > datetime.utcnow() + timedelta(days=13)
                assert lead.expires_at < datetime.utcnow() + timedelta(days=15)
            finally:
                db.close()
        finally:
            delete_lead(email)

    def test_install_link_existing_email_marks_kind_existing():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)
            email = u.email
            with patch("server.send_install_link_email") as sent_new, \
                 patch("server.send_desktop_login_email") as sent_existing:
                r = client.post("/api/install-link", json={"email": email})
                assert r.status_code == 200
                sent_existing.assert_called_once()
                sent_new.assert_not_called()

            lead = db.query(Lead).filter(Lead.email == email).first()
            assert lead is not None
            assert lead.kind == "existing"
            assert lead.expires_at > datetime.utcnow() + timedelta(minutes=14)
            assert lead.expires_at < datetime.utcnow() + timedelta(minutes=16)
        finally:
            if u:
                delete_lead(u.email)
                cleanup(db, u)
            db.close()

    def test_install_link_enumeration_safe():
        """Response is byte-identical whether the email is new or already registered."""
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)
            with patch("server.send_install_link_email"), patch("server.send_desktop_login_email"):
                r_existing = client.post("/api/install-link", json={"email": u.email})
                r_new = client.post("/api/install-link", json={"email": "_lead_enum_new@test.internal"})
            assert r_existing.status_code == r_new.status_code == 200
            assert r_existing.json() == r_new.json() == {"status": "ok"}
        finally:
            delete_lead("_lead_enum_new@test.internal")
            if u:
                delete_lead(u.email)
                cleanup(db, u)
            db.close()

    def test_install_link_detects_existing_account_regardless_of_email_case():
        """/auth/register now lowercases on write, and /api/install-link lowercases on
        read — so a mixed-case-typed registration is still recognised as an existing
        account rather than silently getting offered a second ("new") account."""
        username = "_case_test_user"
        db = SessionLocal()
        u = None
        try:
            r = client.post("/auth/register", json={
                "full_name": "Case Test", "username": username,
                "email": "MixedCase@Test.internal", "password": "Str0ng!Pass",
            })
            assert r.status_code == 200

            u = db.query(User).filter(User.username == username).first()
            assert u is not None
            assert u.email == "mixedcase@test.internal"  # stored lowercase

            with patch("server.send_install_link_email") as sent_new, \
                 patch("server.send_desktop_login_email") as sent_existing:
                r2 = client.post("/api/install-link", json={"email": "mixedcase@test.internal"})
                assert r2.status_code == 200
                sent_existing.assert_called_once()
                sent_new.assert_not_called()

            lead = db.query(Lead).filter(Lead.email == "mixedcase@test.internal").first()
            assert lead is not None
            assert lead.kind == "existing"
        finally:
            delete_lead("mixedcase@test.internal")
            if u:
                cleanup(db, u)
            db.close()

    def test_install_link_honeypot_silently_dropped():
        email = "_lead_honeypot@test.internal"
        try:
            with patch("server.send_install_link_email") as sent:
                r = client.post("/api/install-link", json={"email": email, "hp_check": "Acme Corp"})
                assert r.status_code == 200
                assert r.json() == {"status": "ok"}
                sent.assert_not_called()
            db = SessionLocal()
            try:
                assert db.query(Lead).filter(Lead.email == email).first() is None
            finally:
                db.close()
        finally:
            delete_lead(email)

    def test_install_link_honeypot_still_rate_limited_by_ip():
        """The honeypot check must not let a bot dodge the IP-based limiter — otherwise
        filling every field (including hidden ones) is a free unlimited-request bypass."""
        statuses = []
        for i in range(11):  # install_link_ip limit=10 per 60s window
            r = client.post("/api/install-link",
                             json={"email": f"_hp_ip_{i}@test.internal", "hp_check": "bot"})
            statuses.append(r.status_code)
        assert 429 in statuses

    def test_install_link_honeypot_does_not_consume_email_rate_limit():
        """A honeypot-tripped submission never sends anything, so it must not burn the
        target email's rate-limit budget — that would let an attacker grief a real
        person's ability to request a legitimate link later."""
        email = "_lead_hp_griefing@test.internal"
        try:
            r1 = client.post("/api/install-link", json={"email": email, "hp_check": "bot"})
            assert r1.status_code == 200
            with patch("server.send_install_link_email") as sent:
                r2 = client.post("/api/install-link", json={"email": email})
                assert r2.status_code == 200
                sent.assert_called_once()
        finally:
            delete_lead(email)

    def test_install_link_invalid_email_rejected():
        r = client.post("/api/install-link", json={"email": "not-an-email"})
        assert r.status_code == 400
        assert "detail" in r.json()

    def test_install_link_rerequest_rotates_token():
        email = "_lead_rotate@test.internal"
        try:
            with patch("server.send_install_link_email") as sent:
                client.post("/api/install-link", json={"email": email})
                first_token = sent.call_args[0][1]

            # Simulate enough time passing to clear the per-email cooldown, so the second
            # request isn't itself rejected as a rate limit rather than exercising rotation.
            import asyncio
            import server as srv
            asyncio.run(srv.app.state.redis.delete(f"rl:{email}:install_link_email:last"))

            with patch("server.send_install_link_email") as sent2:
                client.post("/api/install-link", json={"email": email})
                second_token = sent2.call_args[0][1]

            assert first_token != second_token

            db = SessionLocal()
            try:
                assert db.query(Lead).filter(Lead.email == email).count() == 1
                lead = db.query(Lead).filter(Lead.email == email).first()
                assert lead.token_hash == _hash(second_token)
            finally:
                db.close()

            # The old (rotated-out) link is dead.
            r = client.get(f"/claim?token={first_token}", follow_redirects=False)
            assert "link_expired" in r.headers.get("location", "")
        finally:
            delete_lead(email)

    def test_install_link_stores_attribution_from_cookie():
        email = "_lead_attr@test.internal"
        try:
            with patch("server.send_install_link_email"):
                r = client.post(
                    "/api/install-link",
                    json={"email": email},
                    cookies={"ia_attr": "utm_source=google&gclid=abc123"},
                )
                assert r.status_code == 200
            db = SessionLocal()
            try:
                lead = db.query(Lead).filter(Lead.email == email).first()
                assert lead.attribution is not None
                assert "google" in lead.attribution
                assert "abc123" in lead.attribution
            finally:
                db.close()
        finally:
            delete_lead(email)

    def test_install_link_rate_limited_on_rapid_repeat():
        email = "_lead_ratelimit@test.internal"
        try:
            with patch("server.send_install_link_email"):
                r1 = client.post("/api/install-link", json={"email": email})
                r2 = client.post("/api/install-link", json={"email": email})
            assert r1.status_code == 200
            assert r2.status_code == 429
        finally:
            delete_lead(email)

    # ---------------------------------------------------------------------
    # GET /claim
    # ---------------------------------------------------------------------

    def test_claim_new_lead_creates_user_and_redirects_to_app():
        email = "_lead_claim_new@test.internal"
        try:
            with patch("server.send_install_link_email") as sent:
                client.post("/api/install-link", json={"email": email, "interview_date": "2099-01-01"})
                token = sent.call_args[0][1]

            r = client.get(f"/claim?token={token}", follow_redirects=False)
            assert r.status_code in (302, 303, 307)
            assert r.headers.get("location") == "/app"
            assert "session" in r.cookies
            assert r.headers.get("referrer-policy") == "no-referrer"

            db = SessionLocal()
            try:
                u = db.query(User).filter(User.email == email).first()
                assert u is not None
                assert u.email_verified is True
                assert u.account_level == AccountLevel.trial
                assert u.referral_code is not None
                assert u.full_name == ""
                assert u.password_set is False
                assert u.interview_date is not None and u.interview_date.isoformat() == "2099-01-01"
            finally:
                if u:
                    cleanup(db, u)
                db.close()
        finally:
            delete_lead(email)

    def test_claim_new_lead_is_reusable():
        email = "_lead_claim_reuse@test.internal"
        db = None
        u = None
        try:
            with patch("server.send_install_link_email") as sent:
                client.post("/api/install-link", json={"email": email})
                token = sent.call_args[0][1]

            r1 = client.get(f"/claim?token={token}", follow_redirects=False)
            r2 = client.get(f"/claim?token={token}", follow_redirects=False)
            assert r1.headers.get("location") == "/app"
            assert r2.headers.get("location") == "/app"
            assert "session" in r1.cookies and "session" in r2.cookies

            db = SessionLocal()
            users = db.query(User).filter(User.email == email).all()
            assert len(users) == 1
            u = users[0]
            lead = db.query(Lead).filter(Lead.email == email).first()
            assert lead.claim_count == 2
            assert lead.expires_at <= datetime.utcnow() + timedelta(hours=24, minutes=1)
        finally:
            delete_lead(email)
            if u and db:
                cleanup(db, u)
            if db:
                db.close()

    def test_claim_transfers_interview_date_and_ref():
        email = "_lead_claim_ref@test.internal"
        db = SessionLocal()
        referrer = None
        u = None
        try:
            referrer = make_user(db, AccountLevel.trial)
            with patch("server.send_install_link_email") as sent:
                r = client.post("/api/install-link", json={"email": email},
                                cookies={"ref": referrer.referral_code})
                assert r.status_code == 200
                token = sent.call_args[0][1]

            r = client.get(f"/claim?token={token}", follow_redirects=False)
            assert r.headers.get("location") == "/app"

            db.expire_all()
            u = db.query(User).filter(User.email == email).first()
            assert u is not None
            assert u.referred_by_id == referrer.id
            ref_row = db.query(Referral).filter(Referral.referee_id == u.id).first()
            assert ref_row is not None
            assert ref_row.referrer_id == referrer.id
            assert "ref" not in r.cookies
        finally:
            delete_lead(email)
            if u:
                cleanup(db, u)
            if referrer:
                cleanup(db, referrer)
            db.close()

    def test_claim_ref_snapshot_survives_without_live_cookie():
        """A ref cookie present at capture time (phone) still applies at claim (laptop),
        even with no ref cookie on the claiming request — the device-hop case."""
        email = "_lead_claim_ref_snapshot@test.internal"
        db = SessionLocal()
        referrer = None
        u = None
        try:
            referrer = make_user(db, AccountLevel.trial)
            with patch("server.send_install_link_email") as sent:
                client.post("/api/install-link", json={"email": email},
                            cookies={"ref": referrer.referral_code})
                token = sent.call_args[0][1]

            # No `ref` cookie on this request — simulates opening the email on a different device.
            r = client.get(f"/claim?token={token}", follow_redirects=False)
            assert r.headers.get("location") == "/app"

            u = db.query(User).filter(User.email == email).first()
            assert u is not None
            assert u.referred_by_id == referrer.id
        finally:
            delete_lead(email)
            if u:
                cleanup(db, u)
            if referrer:
                cleanup(db, referrer)
            db.close()

    def test_claim_existing_account_logs_in_and_is_single_use():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)
            with patch("server.send_desktop_login_email") as sent:
                client.post("/api/install-link", json={"email": u.email})
                token = sent.call_args[0][1]

            r1 = client.get(f"/claim?token={token}", follow_redirects=False)
            assert r1.headers.get("location") == "/app"
            assert "session" in r1.cookies

            assert db.query(User).filter(User.email == u.email).count() == 1

            r2 = client.get(f"/claim?token={token}", follow_redirects=False)
            assert "link_expired" in r2.headers.get("location", "")
            assert "session" not in r2.cookies
        finally:
            delete_lead(u.email if u else "")
            if u:
                cleanup(db, u)
            db.close()

    def test_claim_expired_token_redirects_to_login_error():
        email = "_lead_claim_expired@test.internal"
        db = SessionLocal()
        try:
            raw = "test_claim_expired_raw_token"
            lead = Lead(
                email=email, token_hash=_hash(raw), kind="new",
                expires_at=datetime.utcnow() - timedelta(hours=1),
            )
            db.add(lead)
            db.commit()

            r = client.get(f"/claim?token={raw}", follow_redirects=False)
            assert "link_expired" in r.headers.get("location", "")
            assert "session" not in r.cookies
        finally:
            delete_lead(email)
            db.close()

    def test_claim_unknown_token_redirects_to_login_error():
        r = client.get("/claim?token=totally_made_up_token_xyz", follow_redirects=False)
        assert "link_expired" in r.headers.get("location", "")

    def test_claim_empty_token_redirects_to_login_error():
        r = client.get("/claim?token=", follow_redirects=False)
        assert "link_expired" in r.headers.get("location", "")

    def test_claim_already_registered_after_lead_issued():
        """Lead issued for an email with no account; a real account is then created via
        another path (e.g. normal signup) before the (still-valid) link is ever clicked."""
        email = "_lead_already_reg@test.internal"
        db = SessionLocal()
        u = None
        try:
            with patch("server.send_install_link_email") as sent:
                client.post("/api/install-link", json={"email": email})
                token = sent.call_args[0][1]

            u = make_user(db, AccountLevel.trial)
            u.email = email
            db.commit()

            r = client.get(f"/claim?token={token}", follow_redirects=False)
            assert "already_registered" in r.headers.get("location", "")
            assert "session" not in r.cookies
        finally:
            delete_lead(email)
            if u:
                cleanup(db, u)
            db.close()

    def test_claim_existing_kind_suspended_user_redirects_to_login_error():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)
            with patch("server.send_desktop_login_email") as sent:
                client.post("/api/install-link", json={"email": u.email})
                token = sent.call_args[0][1]
            u.is_active = False
            db.commit()

            r = client.get(f"/claim?token={token}", follow_redirects=False)
            assert "link_expired" in r.headers.get("location", "")
        finally:
            delete_lead(u.email if u else "")
            if u:
                cleanup(db, u)
            db.close()

    def test_claim_new_lead_max_claims_exhausted():
        email = "_lead_claim_maxed@test.internal"
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial, with_code=True)
            raw = "test_claim_maxed_raw_token"
            lead = Lead(
                email=email, token_hash=_hash(raw), kind="new",
                expires_at=datetime.utcnow() + timedelta(hours=1),
                user_id=u.id, claim_count=5,
            )
            db.add(lead)
            db.commit()

            r = client.get(f"/claim?token={raw}", follow_redirects=False)
            assert "link_expired" in r.headers.get("location", "")
        finally:
            delete_lead(email)
            if u:
                cleanup(db, u)
            db.close()

    # ---------------------------------------------------------------------
    # /finish-signup — the password/name gap /claim otherwise leaves behind
    # ---------------------------------------------------------------------

    def test_app_redirects_to_finish_signup_when_password_not_set():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)
            u.password_set = False
            u.email_verified = True
            db.commit()
            token = create_token(u.id)

            r = client.get("/app", cookies={"session": token}, follow_redirects=False)
            assert r.headers.get("location") == "/finish-signup"

            # Same gate applies to the other funnel pages if hit directly.
            for path in ("/welcome", "/welcome/next", "/onboarding"):
                rp = client.get(path, cookies={"session": token}, follow_redirects=False)
                assert rp.headers.get("location") == "/finish-signup", path
        finally:
            if u:
                cleanup(db, u)
            db.close()

    def test_finish_signup_requires_auth():
        r = client.get("/finish-signup", follow_redirects=False)
        assert r.status_code in (302, 303, 307)
        assert "/login" in r.headers.get("location", "")

    def test_finish_signup_page_redirects_if_already_set():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)  # password_set defaults True
            token = create_token(u.id)
            r = client.get("/finish-signup", cookies={"session": token}, follow_redirects=False)
            assert r.headers.get("location") == "/app"
        finally:
            if u:
                cleanup(db, u)
            db.close()

    def test_finish_signup_post_rejects_when_already_set():
        """The POST route must independently refuse once password_set is True — it has no
        current-password check, so without this guard anyone holding a valid session cookie
        could silently overwrite ANY user's password, not just a fresh /claim account's."""
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)  # password_set defaults True
            original_hash = u.password_hash
            token = create_token(u.id)
            r = client.post("/api/finish-signup",
                             json={"full_name": "Attacker Name", "password": "Str0ng!Pass"},
                             cookies={"session": token})
            assert r.status_code == 403
            db.expire(u)
            db.refresh(u)
            assert u.password_hash == original_hash
            assert u.full_name != "Attacker Name"
        finally:
            if u:
                cleanup(db, u)
            db.close()

    def test_finish_signup_page_renders_when_not_set():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)
            u.password_set = False
            db.commit()
            token = create_token(u.id)
            r = client.get("/finish-signup", cookies={"session": token})
            assert r.status_code == 200
            assert "finish-form" in r.text
        finally:
            if u:
                cleanup(db, u)
            db.close()

    def test_finish_signup_weak_password_rejected():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)
            u.password_set = False
            db.commit()
            token = create_token(u.id)
            r = client.post("/api/finish-signup",
                             json={"full_name": "Test Name", "password": "weak"},
                             cookies={"session": token})
            assert r.status_code == 400
            db.expire(u)
            assert u.password_set is False
        finally:
            if u:
                cleanup(db, u)
            db.close()

    def test_finish_signup_blank_name_rejected():
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)
            u.password_set = False
            db.commit()
            token = create_token(u.id)
            r = client.post("/api/finish-signup",
                             json={"full_name": "   ", "password": "Str0ng!Pass"},
                             cookies={"session": token})
            assert r.status_code == 400
            db.expire(u)
            assert u.password_set is False
        finally:
            if u:
                cleanup(db, u)
            db.close()

    def test_finish_signup_success_completes_the_full_chain():
        """End to end: /claim -> gated at /app -> /finish-signup -> back to /app -> /welcome,
        same destination a normal registration would reach, now with a real password set."""
        email = "_lead_finish_e2e@test.internal"
        db = SessionLocal()
        u = None
        try:
            with patch("server.send_install_link_email") as sent:
                client.post("/api/install-link", json={"email": email})
                token = sent.call_args[0][1]

            claim_resp = client.get(f"/claim?token={token}", follow_redirects=False)
            assert claim_resp.headers.get("location") == "/app"
            session_cookie = claim_resp.cookies["session"]

            gated = client.get("/app", cookies={"session": session_cookie}, follow_redirects=False)
            assert gated.headers.get("location") == "/finish-signup"

            finish = client.post("/api/finish-signup",
                                  json={"password": "Str0ng!Pass", "full_name": "Ada Lovelace"},
                                  cookies={"session": session_cookie})
            assert finish.status_code == 200

            u = db.query(User).filter(User.email == email).first()
            assert u.password_set is True
            assert u.full_name == "Ada Lovelace"
            from auth import verify_password
            assert verify_password("Str0ng!Pass", u.password_hash)

            resumed = client.get("/app", cookies={"session": session_cookie}, follow_redirects=False)
            assert resumed.headers.get("location") == "/welcome"
        finally:
            delete_lead(email)
            if u:
                cleanup(db, u)
            db.close()

    def test_reset_password_also_satisfies_the_gate():
        """A claim account that uses "forgot password" instead of /finish-signup should be
        equally unblocked — either path proves the same thing."""
        db = SessionLocal()
        u = None
        try:
            u = make_user(db, AccountLevel.trial)
            u.password_set = False
            u.reset_token = "test_finish_via_reset_token"
            from datetime import timedelta as _td
            u.reset_token_expiry = datetime.utcnow() + _td(hours=1)
            db.commit()

            r = client.post("/auth/reset-password", json={
                "token": "test_finish_via_reset_token", "new_password": "Str0ng!Pass2",
            })
            assert r.status_code == 200

            db.expire(u)
            db.refresh(u)
            assert u.password_set is True
        finally:
            if u:
                cleanup(db, u)
            db.close()

    def test_claim_interview_date_triggers_existing_reminder_job():
        """Proves the whole chain end to end: a date captured at /api/install-link, carried
        onto the User at /claim, is picked up by the SAME sweep (_send_due_interview_reminders)
        that handles every other account — no special-casing needed for claim-created users."""
        import server as srv

        email = "_lead_reminder_e2e@test.internal"
        db = SessionLocal()
        u = None
        try:
            tomorrow = (datetime.utcnow() + timedelta(days=1)).date()
            with patch("server.send_install_link_email") as sent:
                client.post("/api/install-link",
                            json={"email": email, "interview_date": tomorrow.isoformat()})
                token = sent.call_args[0][1]

            client.get(f"/claim?token={token}", follow_redirects=False)

            u = db.query(User).filter(User.email == email).first()
            assert u is not None
            assert u.interview_date == tomorrow
            assert u.interview_reminder_sent is False

            with patch("server.send_interview_reminder_email") as reminder_sent:
                srv._send_due_interview_reminders()
            reminder_sent.assert_any_call(email, "")

            db.expire(u)
            db.refresh(u)
            assert u.interview_reminder_sent is True
        finally:
            delete_lead(email)
            if u:
                cleanup(db, u)
            db.close()

    # ---------------------------------------------------------------------
    # Landing page
    # ---------------------------------------------------------------------

    def test_landing_page_has_lead_form():
        r = client.get("/")
        assert r.status_code == 200
        assert 'id="lead-form"' in r.text
        assert 'name="hp_check"' in r.text

    def test_landing_sets_attribution_cookie_first_touch_only():
        r1 = client.get("/?utm_source=google&gclid=abc123")
        assert "ia_attr" in r1.cookies
        cookie_val = r1.cookies["ia_attr"]

        r2 = client.get("/?utm_source=bing", cookies={"ia_attr": cookie_val})
        assert "ia_attr" not in r2.cookies  # already set — must not be overwritten

    test("_rotate_lead_token: unclaimed lead gets new token, no first-touch overwrite", test_rotate_lead_token_on_unclaimed_lead)
    test("_rotate_lead_token: lead whose email now has a User -> kind=existing",        test_rotate_lead_token_on_lead_with_existing_account)
    test("_rotate_lead_token: clears claimed_at/claim_count",                           test_rotate_lead_token_clears_claim_bookkeeping)
    test("POST /api/install-link: new email creates a Lead",              test_install_link_new_email_creates_lead)
    test("POST /api/install-link: existing email marks kind=existing",    test_install_link_existing_email_marks_kind_existing)
    test("POST /api/install-link: response is enumeration-safe",          test_install_link_enumeration_safe)
    test("POST /api/install-link: detects existing account by email regardless of case", test_install_link_detects_existing_account_regardless_of_email_case)
    test("POST /api/install-link: honeypot silently dropped",             test_install_link_honeypot_silently_dropped)
    test("POST /api/install-link: honeypot still IP rate limited",        test_install_link_honeypot_still_rate_limited_by_ip)
    test("POST /api/install-link: honeypot doesn't burn email's budget",  test_install_link_honeypot_does_not_consume_email_rate_limit)
    test("POST /api/install-link: invalid email rejected",                test_install_link_invalid_email_rejected)
    test("POST /api/install-link: re-request rotates the token",          test_install_link_rerequest_rotates_token)
    test("POST /api/install-link: ia_attr cookie stored as attribution",  test_install_link_stores_attribution_from_cookie)
    test("POST /api/install-link: rapid repeat is rate limited",          test_install_link_rate_limited_on_rapid_repeat)
    test("GET /claim: new lead creates user, redirects to /app",          test_claim_new_lead_creates_user_and_redirects_to_app)
    test("GET /claim: new-lead token is reusable",                       test_claim_new_lead_is_reusable)
    test("GET /claim: transfers interview_date + applies ref cookie",     test_claim_transfers_interview_date_and_ref)
    test("GET /claim: ref snapshot survives without live cookie",         test_claim_ref_snapshot_survives_without_live_cookie)
    test("GET /claim: existing-account token logs in, single-use",       test_claim_existing_account_logs_in_and_is_single_use)
    test("GET /claim: expired token -> login?error=link_expired",        test_claim_expired_token_redirects_to_login_error)
    test("GET /claim: unknown token -> login?error=link_expired",        test_claim_unknown_token_redirects_to_login_error)
    test("GET /claim: empty token -> login?error=link_expired",          test_claim_empty_token_redirects_to_login_error)
    test("GET /claim: already_registered after lead issued",             test_claim_already_registered_after_lead_issued)
    test("GET /claim: suspended existing-account user -> link_expired",  test_claim_existing_kind_suspended_user_redirects_to_login_error)
    test("GET /claim: new-lead max claims exhausted -> link_expired",     test_claim_new_lead_max_claims_exhausted)
    test("GET /app,/welcome,/onboarding gate on password_set",           test_app_redirects_to_finish_signup_when_password_not_set)
    test("GET /finish-signup requires auth",                            test_finish_signup_requires_auth)
    test("GET /finish-signup redirects to /app if already set",         test_finish_signup_page_redirects_if_already_set)
    test("POST /api/finish-signup rejects when already set",            test_finish_signup_post_rejects_when_already_set)
    test("GET /finish-signup renders when password not set",            test_finish_signup_page_renders_when_not_set)
    test("POST /api/finish-signup: weak password rejected",             test_finish_signup_weak_password_rejected)
    test("POST /api/finish-signup: blank name rejected",                 test_finish_signup_blank_name_rejected)
    test("POST /api/finish-signup: full chain claim -> app -> welcome",  test_finish_signup_success_completes_the_full_chain)
    test("POST /auth/reset-password also satisfies the password gate",  test_reset_password_also_satisfies_the_gate)
    test("Claimed interview_date reaches the existing reminder job",    test_claim_interview_date_triggers_existing_reminder_job)
    test("GET /: landing page contains the mobile lead-capture form",    test_landing_page_has_lead_form)
    test("GET /: ia_attr cookie set once, first touch wins",             test_landing_sets_attribution_cookie_first_touch_only)
