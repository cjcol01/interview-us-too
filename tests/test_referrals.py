import secrets as _sec
from unittest.mock import patch

from database import SessionLocal, init_db
from models import AccountLevel, Referral, ReferralStatus, User
from tests.helpers import cleanup, delete_by_name, make_cookie, make_user


def register(test, skip, client):

    # -- /r/{code} route -----------------------------------------------------

    def test_valid_referral_link_sets_cookie():
        init_db()
        db = SessionLocal()
        try:
            referrer = make_user(db)
            code = referrer.referral_code
            r = client.get(f"/r/{code}", follow_redirects=False)
            assert r.status_code in (302, 307)
            assert "location" in r.headers
            assert r.cookies.get("ref") == code or "ref" in r.headers.get("set-cookie", "")
        finally:
            cleanup(db, referrer); db.close()

    def test_invalid_referral_link_no_cookie():
        r = client.get("/r/nonexistentcode123", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "ref" not in r.cookies

    def test_referral_link_when_logged_in_redirects_to_app():
        from models import AccountLevel
        token, uname = make_cookie(AccountLevel.trial)
        try:
            db = SessionLocal()
            u = db.query(User).filter(User.username == uname).first()
            code = u.referral_code
            db.close()
            r = client.get(f"/r/{code}", cookies={"session": token}, follow_redirects=False)
            assert r.status_code in (302, 307)
            assert "/app" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    # -- Registration with referral cookie -----------------------------------

    def test_register_assigns_referral_code():
        tag = _sec.token_hex(4)
        uname = f"_ref_reg_{tag}"
        r = client.post("/auth/register", json={
            "full_name": "Ref Test", "username": uname,
            "email": f"{uname}@test.internal", "password": "testpassword123",
        })
        try:
            assert r.status_code == 200
            db = SessionLocal()
            try:
                u = db.query(User).filter(User.username == uname).first()
                assert u is not None
                assert u.referral_code is not None and len(u.referral_code) > 0
            finally:
                db.close()
        finally:
            delete_by_name(uname)

    def test_register_with_ref_cookie_creates_referral_row():
        init_db()
        db = SessionLocal()
        referrer = make_user(db)
        tag = _sec.token_hex(4)
        referee_uname = f"_ref_cookie_{tag}"
        try:
            r = client.post(
                "/auth/register",
                json={
                    "full_name": "Referee", "username": referee_uname,
                    "email": f"{referee_uname}@test.internal", "password": "testpassword123",
                },
                cookies={"ref": referrer.referral_code},
            )
            assert r.status_code == 200
            db2 = SessionLocal()
            try:
                referee = db2.query(User).filter(User.username == referee_uname).first()
                assert referee is not None
                assert referee.referred_by_id == referrer.id
                ref_row = db2.query(Referral).filter(Referral.referee_id == referee.id).first()
                assert ref_row is not None
                assert ref_row.referrer_id == referrer.id
                assert ref_row.status == ReferralStatus.signed_up
            finally:
                cleanup(db2, referee)
                db2.close()
        finally:
            cleanup(db, referrer)
            db.close()

    def test_register_with_invalid_ref_cookie_no_referral():
        tag = _sec.token_hex(4)
        uname = f"_ref_invalid_{tag}"
        try:
            r = client.post(
                "/auth/register",
                json={
                    "full_name": "No Ref", "username": uname,
                    "email": f"{uname}@test.internal", "password": "testpassword123",
                },
                cookies={"ref": "invalidcode999"},
            )
            assert r.status_code == 200
            db = SessionLocal()
            try:
                u = db.query(User).filter(User.username == uname).first()
                assert u.referred_by_id is None
                assert db.query(Referral).filter(Referral.referee_id == u.id).first() is None
            finally:
                db.close()
        finally:
            delete_by_name(uname)

    def test_register_with_others_code_creates_referral():
        # Using someone else's referral code at registration SHOULD create a referral.
        # There is no way to block "self-referral via a second account" at the server
        # level (the two accounts have different IDs). The real self-referral guard
        # lives at POST /referral/apply (server.py:441-442).
        token, uname = make_cookie(AccountLevel.trial)
        db = SessionLocal()
        u = db.query(User).filter(User.username == uname).first()
        own_code = u.referral_code
        db.close()
        try:
            tag = _sec.token_hex(4)
            new_uname = f"_self_ref_{tag}"
            r = client.post(
                "/auth/register",
                json={
                    "full_name": "Self", "username": new_uname,
                    "email": f"{new_uname}@test.internal", "password": "testpassword123",
                },
                cookies={"ref": own_code},
            )
            assert r.status_code == 200
            db2 = SessionLocal()
            try:
                new_u = db2.query(User).filter(User.username == new_uname).first()
                # referral IS created — different accounts, different IDs
                assert new_u.referred_by_id == u.id
            finally:
                cleanup(db2, new_u)
                db2.close()
        finally:
            delete_by_name(uname)

    def test_referral_apply_blocks_self_referral():
        # /referral/apply DOES guard self-referral (server.py:441-442).
        token, uname = make_cookie(AccountLevel.trial)
        db = SessionLocal()
        u = db.query(User).filter(User.username == uname).first()
        own_code = u.referral_code
        db.close()
        try:
            r = client.post(
                "/referral/apply",
                data={"code": own_code, "source": "settings"},
                cookies={"session": token},
                follow_redirects=False,
            )
            assert r.status_code in (302, 303, 307)
            assert "self_referral" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    # -- /referral page ------------------------------------------------------

    def test_referral_page_requires_auth():
        r = client.get("/referral", follow_redirects=False)
        assert r.status_code in (302, 307)
        assert "login" in r.headers.get("location", "")

    def test_referral_page_shows_code():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/referral", cookies={"session": token})
            assert r.status_code == 200
            db = SessionLocal()
            try:
                u = db.query(User).filter(User.username == uname).first()
                assert u.referral_code in r.text
            finally:
                db.close()
        finally:
            delete_by_name(uname)

    def test_referral_page_empty_list_for_new_user():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.get("/referral", cookies={"session": token})
            assert r.status_code == 200
            assert "No referrals yet" in r.text
        finally:
            delete_by_name(uname)

    def test_referral_page_shows_referee():
        init_db()
        db = SessionLocal()
        referrer = make_user(db, AccountLevel.unlimited)
        referee = make_user(db, AccountLevel.trial)
        referee.referred_by_id = referrer.id
        ref_row = Referral(referrer_id=referrer.id, referee_id=referee.id)
        db.add(ref_row)
        db.commit()
        try:
            from auth import create_token
            token = create_token(referrer.id)
            r = client.get("/referral", cookies={"session": token})
            assert r.status_code == 200
            assert referee.username in r.text
        finally:
            cleanup(db, referrer, referee)
            db.close()

    # -- Checkout discount for referred users --------------------------------

    def test_checkout_applies_discount_for_referred_user():
        from unittest.mock import MagicMock
        init_db()
        db = SessionLocal()
        referrer = make_user(db)
        referee = make_user(db, AccountLevel.trial)
        referee.referred_by_id = referrer.id
        ref_row = Referral(referrer_id=referrer.id, referee_id=referee.id)
        db.add(ref_row)
        db.commit()
        try:
            from auth import create_token
            token = create_token(referee.id)
            mock_session = MagicMock()
            mock_session.url = "https://checkout.stripe.com/pay/test"
            captured = {}
            def capture_create(**kwargs):
                captured.update(kwargs)
                return mock_session
            with patch("billing.stripe.checkout.Session.create", side_effect=capture_create), \
                 patch("billing.stripe.Customer.create", return_value=MagicMock(id=f"cus_{_sec.token_hex(4)}")):
                r = client.get("/billing/checkout?plan=subscription",
                               cookies={"session": token},
                               follow_redirects=False)
            assert r.status_code in (302, 307)
            assert "discounts" in captured, "discount not passed to Stripe for referred user"
        finally:
            cleanup(db, referrer, referee)
            db.close()

    def test_checkout_no_discount_for_non_referred_user():
        from unittest.mock import MagicMock
        init_db()
        db = SessionLocal()
        user = make_user(db, AccountLevel.trial)
        try:
            from auth import create_token
            token = create_token(user.id)
            captured = {}
            mock_session = MagicMock()
            mock_session.url = "https://checkout.stripe.com/pay/test"
            def capture_create(**kwargs):
                captured.update(kwargs)
                return mock_session
            with patch("billing.stripe.checkout.Session.create", side_effect=capture_create), \
                 patch("billing.stripe.Customer.create", return_value=MagicMock(id=f"cus_{_sec.token_hex(4)}")):
                r = client.get("/billing/checkout?plan=subscription",
                               cookies={"session": token},
                               follow_redirects=False)
            assert r.status_code in (302, 307)
            assert "discounts" not in captured, "discount incorrectly applied to non-referred user"
        finally:
            cleanup(db, user)
            db.close()

    test("/r/{code} valid → sets ref cookie",                          test_valid_referral_link_sets_cookie)
    test("/r/{code} invalid → no cookie, still redirects",            test_invalid_referral_link_no_cookie)
    test("/r/{code} when logged in → redirects to /app",              test_referral_link_when_logged_in_redirects_to_app)
    test("Register assigns referral_code to new user",                 test_register_assigns_referral_code)
    test("Register with ref cookie creates Referral row",             test_register_with_ref_cookie_creates_referral_row)
    test("Register with invalid ref cookie → no referral created",    test_register_with_invalid_ref_cookie_no_referral)
    test("Register with own code creates referral (2nd account)",     test_register_with_others_code_creates_referral)
    test("/referral/apply blocks self-referral",                      test_referral_apply_blocks_self_referral)
    test("/referral requires auth",                                    test_referral_page_requires_auth)
    test("/referral shows user's referral code",                       test_referral_page_shows_code)
    test("/referral shows empty state for new user",                   test_referral_page_empty_list_for_new_user)
    test("/referral shows referee in list",                            test_referral_page_shows_referee)
    test("Checkout applies discount for referred subscriber",          test_checkout_applies_discount_for_referred_user)
    test("Checkout skips discount for non-referred user",              test_checkout_no_discount_for_non_referred_user)

    # -- /referral/apply happy path and edge cases ---------------------------

    def test_referral_apply_valid_code_creates_referral():
        init_db()
        db = SessionLocal()
        referrer = make_user(db, AccountLevel.unlimited)
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.post(
                "/referral/apply",
                data={"code": referrer.referral_code, "source": "settings"},
                cookies={"session": token},
                follow_redirects=False,
            )
            assert r.status_code in (302, 303, 307)
            assert "ref_success=1" in r.headers.get("location", "")
            db2 = SessionLocal()
            try:
                applicant = db2.query(User).filter(User.username == uname).first()
                assert applicant.referred_by_id == referrer.id
                ref_row = db2.query(Referral).filter(Referral.referee_id == applicant.id).first()
                assert ref_row is not None
                assert ref_row.referrer_id == referrer.id
                assert ref_row.status == ReferralStatus.signed_up
            finally:
                db2.close()
        finally:
            cleanup(db, referrer); db.close()
            delete_by_name(uname)

    def test_referral_apply_already_referred_is_rejected():
        init_db()
        db = SessionLocal()
        referrer = make_user(db, AccountLevel.unlimited)
        token, uname = make_cookie(AccountLevel.trial)
        try:
            applicant = db.query(User).filter(User.username == uname).first()
            applicant.referred_by_id = referrer.id
            db.commit()
            r = client.post(
                "/referral/apply",
                data={"code": referrer.referral_code, "source": "settings"},
                cookies={"session": token},
                follow_redirects=False,
            )
            assert r.status_code in (302, 303, 307)
            assert "already_referred" in r.headers.get("location", "")
        finally:
            cleanup(db, referrer); db.close()
            delete_by_name(uname)

    def test_referral_apply_invalid_code_is_rejected():
        token, uname = make_cookie(AccountLevel.trial)
        try:
            r = client.post(
                "/referral/apply",
                data={"code": "zzz_totally_nonexistent_code", "source": "settings"},
                cookies={"session": token},
                follow_redirects=False,
            )
            assert r.status_code in (302, 303, 307)
            assert "invalid_code" in r.headers.get("location", "")
        finally:
            delete_by_name(uname)

    def test_referral_apply_url_form_code_is_parsed():
        """_parse_referral_code accepts a full /r/CODE URL."""
        init_db()
        db = SessionLocal()
        referrer = make_user(db, AccountLevel.unlimited)
        token, uname = make_cookie(AccountLevel.trial)
        try:
            url_code = f"https://example.com/r/{referrer.referral_code}"
            r = client.post(
                "/referral/apply",
                data={"code": url_code, "source": "settings"},
                cookies={"session": token},
                follow_redirects=False,
            )
            assert r.status_code in (302, 303, 307)
            assert "ref_success=1" in r.headers.get("location", "")
        finally:
            cleanup(db, referrer); db.close()
            delete_by_name(uname)

    test("/referral/apply: valid code creates referral row",          test_referral_apply_valid_code_creates_referral)
    test("/referral/apply: already referred is rejected",             test_referral_apply_already_referred_is_rejected)
    test("/referral/apply: invalid code is rejected",                 test_referral_apply_invalid_code_is_rejected)
    test("/referral/apply: URL-form /r/CODE is parsed correctly",     test_referral_apply_url_form_code_is_parsed)
