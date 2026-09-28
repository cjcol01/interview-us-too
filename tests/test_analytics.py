"""PostHog analytics wiring: the suite must never send events (analytics._ph is None under
TESTING), and when a sink is swapped in, the server-side events carry the right distinct id
(numeric user id, or the browser's anonymous id from the posthog-js cookie), the browser
$session_id, and the person-profile / attribution writes the funnels depend on."""
import hashlib
import json
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote


class _Sink:
    """Stand-in for the posthog-python client: records every call instead of sending."""
    def __init__(self):
        self.captures, self.sets, self.set_onces, self.aliases = [], [], [], []

    def capture(self, event, distinct_id=None, properties=None):
        self.captures.append((event, distinct_id, properties or {}))

    def set(self, distinct_id=None, properties=None):
        self.sets.append((distinct_id, properties or {}))

    def set_once(self, distinct_id=None, properties=None):
        self.set_onces.append((distinct_id, properties or {}))

    def alias(self, previous_id=None, distinct_id=None):
        self.aliases.append((previous_id, distinct_id))

    def events(self, name):
        return [c for c in self.captures if c[0] == name]


_COOKIE = "ph_test_posthog"


def _ph_cookie(distinct_id="anon-1", session_id="sess-1", age_ms=0):
    now_ms = int(time.time() * 1000)
    return quote(json.dumps({"distinct_id": distinct_id, "$sesid": [now_ms - age_ms, session_id, now_ms - age_ms]}))


def _raise(*args, **kwargs):
    raise RuntimeError("provider unavailable")


class _FakeOpenAIStream:
    def __init__(self, pieces):
        self._pieces = pieces

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for piece in self._pieces:
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content=piece))])


def register(test, skip, client):
    import analytics
    from auth import create_token
    from database import SessionLocal
    from models import AccountLevel, Lead, User
    from tests.helpers import cleanup, delete_lead, make_user

    class _sink:
        """Context manager: swap a _Sink into analytics for the duration of a test."""
        def __enter__(self):
            self.s = _Sink()
            analytics._ph = self.s
            analytics._COOKIE_NAME = _COOKIE
            return self.s

        def __exit__(self, *a):
            analytics._ph = None
            analytics._COOKIE_NAME = None

    # -- 1. the suite itself never sends ---------------------------------------------------
    def test_suite_never_sends_to_posthog():
        assert analytics._ph is None
        assert os.environ.get("POSTHOG_API_KEY") == ""
        assert analytics.cookie_name() is None
        # and the wrappers are silent no-ops rather than raising
        analytics.track(1, "x")
        analytics.track(None, "x")
        analytics.set_once(1, a=1)
        analytics.alias("anon", 1)

    # -- 2. anonymous events without a browser cookie are dropped -------------------------
    def test_track_without_user_or_cookie_is_dropped():
        with _sink() as s:
            analytics.track(None, "orphan")
            assert s.captures == []
            analytics.track(7, "kept", foo="bar")
            assert s.captures == [("kept", "7", {"foo": "bar"})]

    # -- 3. browser $session_id reaches server-side events (contextvar → threadpool) ------
    def test_session_id_attached_from_cookie():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            with _sink() as s:
                r = client.get("/pricing", cookies={"session": create_token(u.id), _COOKIE: _ph_cookie()})
                assert r.status_code == 200
                ev = s.events("pricing_viewed")
                assert len(ev) == 1 and ev[0][1] == str(u.id), s.captures
                assert ev[0][2].get("$session_id") == "sess-1"
        finally:
            cleanup(db, u)

    def test_stale_session_id_not_attached():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            with _sink() as s:
                stale = _ph_cookie(age_ms=45 * 60 * 1000)
                r = client.get("/pricing", cookies={"session": create_token(u.id), _COOKIE: stale})
                assert r.status_code == 200
                ev = s.events("pricing_viewed")
                assert len(ev) == 1 and "$session_id" not in ev[0][2]
        finally:
            cleanup(db, u)

    def test_malformed_cookie_is_ignored():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            with _sink() as s:
                r = client.get("/pricing", cookies={"session": create_token(u.id), _COOKIE: "%7Bnot-json"})
                assert r.status_code == 200
                assert len(s.events("pricing_viewed")) == 1
        finally:
            cleanup(db, u)

    # -- 4. anonymous server events land on the browser id, without a person profile ------
    def test_anonymous_contact_uses_browser_distinct_id():
        with _sink() as s, patch("server.send_contact_email"):
            r = client.post("/api/contact", json={"dept": "support", "from_email": "a@b.co",
                                                  "subject": "hi", "message": "hello"},
                            cookies={_COOKIE: _ph_cookie(distinct_id="anon-42")})
            assert r.status_code == 200, r.text
            ev = s.events("contact_submitted")
            assert len(ev) == 1
            assert ev[0][1] == "anon-42"
            assert ev[0][2]["$process_person_profile"] is False
            assert ev[0][2]["logged_in"] is False
            assert "from_email" not in ev[0][2] and "message" not in ev[0][2]

    # -- 5. login failures ----------------------------------------------------------------
    def test_login_failed_reasons():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            with _sink() as s:
                r = client.post("/auth/login", json={"username": u.username, "password": "wrong"})
                assert r.status_code == 401
                ev = s.events("login_failed")
                assert ev and ev[-1][1] == str(u.id) and ev[-1][2]["reason"] == "invalid"

                r = client.post("/auth/login", json={"username": "_nobody_here_", "password": "x"},
                                cookies={_COOKIE: _ph_cookie(distinct_id="anon-9")})
                assert r.status_code == 401
                ev = s.events("login_failed")
                assert ev[-1][1] == "anon-9" and ev[-1][2]["reason"] == "invalid"

                u.is_active = False
                db.commit()
                r = client.post("/auth/login", json={"username": u.username, "password": "testpass123"})
                assert r.status_code == 403
                ev = s.events("login_failed")
                assert ev[-1][1] == str(u.id) and ev[-1][2]["reason"] == "suspended"

                # a successful login still fires the existing `login` event, not a failure
                u.is_active = True
                db.commit()
                r = client.post("/auth/login", json={"username": u.username, "password": "testpass123"})
                assert r.status_code == 200
                assert s.events("login")[-1][1] == str(u.id)
        finally:
            cleanup(db, u)

    # -- 6. extension_connected fires exactly once ----------------------------------------
    def test_extension_connected_once():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            with _sink() as s:
                for _ in range(3):
                    r = client.post("/api/ext/status", json={"ext": True, "ext_enabled": True, "mic": "granted"},
                                    headers={"Authorization": f"Bearer {u.api_token}"})
                    assert r.status_code == 200
                ev = s.events("extension_connected")
                assert len(ev) == 1 and ev[0][1] == str(u.id) and ev[0][2]["ext_enabled"] is True
                # profile refreshed with the activation flag
                assert any(sid == str(u.id) and props.get("ext_connected") is True for sid, props in s.sets)
            db.refresh(u)
            assert u.ext_first_seen_at is not None
        finally:
            cleanup(db, u)

    # -- 7. device-hop signup: attribution + alias -----------------------------------------
    def test_claim_writes_attribution_and_aliases_phone_id():
        email = "_lead_analytics_claim@test.internal"
        try:
            with _sink() as s, patch("server.send_install_link_email") as sent:
                r = client.post("/api/install-link", json={"email": email},
                                cookies={_COOKIE: _ph_cookie(distinct_id="phone-anon-1"),
                                         "ia_attr": "utm_source=google&utm_campaign=spring&gclid=abc123&r=https%3A%2F%2Fwww.google.com%2F"})
                assert r.status_code == 200
                token = sent.call_args[0][1]
                req = s.events("install_link_requested")
                assert len(req) == 1 and req[0][1] == "phone-anon-1" and req[0][2]["has_attribution"] is True

                db = SessionLocal()
                try:
                    lead = db.query(Lead).filter(Lead.email == email).first()
                    assert lead.ph_distinct_id == "phone-anon-1"
                finally:
                    db.close()

                # the laptop: a different browser, no ia_attr, no posthog cookie
                client.cookies.clear()
                r = client.get(f"/claim?token={token}", follow_redirects=False)
                assert r.status_code in (302, 303)

                db = SessionLocal()
                try:
                    u = db.query(User).filter(User.email == email).first()
                    assert u is not None
                    uid = str(u.id)
                    assert ("phone-anon-1", uid) in s.aliases
                    once = [p for sid, p in s.set_onces if sid == uid]
                    assert once, s.set_onces
                    once = once[0]
                    assert once["signup_method"] == "install_link"
                    assert once["$initial_utm_source"] == "google"
                    assert once["$initial_utm_campaign"] == "spring"
                    assert once["$initial_gclid"] == "abc123"
                    assert once["$initial_referring_domain"] == "www.google.com"
                    assert s.events("signup")[-1][2]["method"] == "install_link"
                    assert any(sid == uid and p.get("email") == email for sid, p in s.sets)
                finally:
                    if u:
                        cleanup(db, u)
                    db.close()
        finally:
            delete_lead(email)

    def test_register_writes_attribution_from_cookie():
        uname = "_analytics_reg_user"
        email = "_analytics_reg@test.internal"
        db = SessionLocal()
        u = None
        try:
            with _sink() as s:
                r = client.post("/auth/register",
                                json={"username": uname, "email": email, "full_name": "Reg Test",
                                      "password": "TestPass123!"},
                                cookies={"ia_attr": "utm_source=meta&fbclid=fb9"})
                assert r.status_code == 200, r.text
                u = db.query(User).filter(User.email == email).first()
                assert u is not None
                once = [p for sid, p in s.set_onces if sid == str(u.id)][0]
                assert once["signup_method"] == "password"
                assert once["$initial_utm_source"] == "meta" and once["$initial_fbclid"] == "fb9"
                assert "$initial_referrer" not in once
                assert s.events("signup")[-1][2]["method"] == "password"
                assert "ia_attr" in r.headers.get("set-cookie", "")  # deleted after use
        finally:
            cleanup(db, u)

    # -- 8. subscription lifecycle events ---------------------------------------------------
    def test_subscription_created_fires_only_on_activation():
        from billing import _sync_subscription
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial, stripe_id="cus_analytics_1")
            with _sink() as s:
                def sub(status, **extra):
                    return {"id": "sub_analytics_1", "customer": "cus_analytics_1", "status": status,
                            "cancel_at_period_end": False, "cancel_at": None, "trial_end": None, **extra}
                _sync_subscription(sub("trialing"), db)
                assert len(s.events("subscription_created")) == 1
                _sync_subscription(sub("active"), db)                     # trial → paid flip
                _sync_subscription(sub("active", cancel_at_period_end=True), db)  # cancel toggle
                assert len(s.events("subscription_created")) == 1, s.captures
                assert len(s.events("subscription_updated")) == 2
                _sync_subscription(sub("canceled"), db)
                assert len(s.events("subscription_lapsed")) == 1
                # person profile refreshed after every sync
                levels = [p["account_level"] for sid, p in s.sets if sid == str(u.id)]
                assert levels[0] == "unlimited" and levels[-1] == "free"
        finally:
            cleanup(db, u)

    def test_invoice_paid_events():
        from billing import _handle_invoice_paid
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.unlimited, stripe_id="cus_analytics_2")
            with _sink() as s:
                inv = {"customer": "cus_analytics_2", "amount_paid": 1500, "id": "in_1",
                       "billing_reason": "subscription_create", "starting_balance": 0, "ending_balance": 0}
                _handle_invoice_paid(inv, db)
                assert s.events("subscription_first_invoice_paid")[0][2]["amount_pence"] == 1500
                inv2 = dict(inv, id="in_2", billing_reason="subscription_cycle")
                _handle_invoice_paid(inv2, db)
                assert len(s.events("subscription_first_invoice_paid")) == 1
                assert s.events("subscription_renewed")[0][2]["amount_pence"] == 1500
        finally:
            cleanup(db, u)

    # -- 9. uninstall landing page --------------------------------------------------------
    def test_extension_uninstalled_anonymous_vs_signed_in():
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            with _sink() as s:
                r = client.get("/extension/uninstalled?v=1.2")
                assert r.status_code == 200
                assert "iwTrack('extension_uninstalled'" in r.text
                assert s.events("extension_uninstalled") == []

                r = client.get("/extension/uninstalled?v=1.2", cookies={"session": create_token(u.id)})
                assert r.status_code == 200
                assert "iwTrack('extension_uninstalled'" not in r.text
                ev = s.events("extension_uninstalled")
                assert len(ev) == 1 and ev[0][1] == str(u.id) and ev[0][2]["ext_version"] == "1.2"
        finally:
            cleanup(db, u)

    # -- 10. paid session start + AI failover -----------------------------------------------
    def test_session_started_and_ai_failover_on_text_capture():
        import server
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.paid)
            u.sessions_remaining = 1
            db.commit()
            orig_stream = server.async_client.messages.stream
            orig_openai = server.openai_async_client.chat.completions.create
            server.async_client.messages.stream = _raise
            server.openai_async_client.chat.completions.create = AsyncMock(
                return_value=_FakeOpenAIStream(["fallback ", "answer"]))
            try:
                with _sink() as s:
                    r = client.post("/api/text-capture", json={"text": "What is a hash map?"},
                                    headers={"Authorization": f"Bearer {u.api_token}"})
                    assert r.status_code == 200, r.text
                    names = [c[0] for c in s.captures]
                    assert "session_started" in names and "ai_failover" in names and "text_capture_submitted" in names
                    assert names.index("session_started") < names.index("text_capture_submitted")
                    ss = s.events("session_started")[0]
                    assert ss[1] == str(u.id) and ss[2]["source"] == "text"
                    fo = s.events("ai_failover")[0][2]
                    assert fo["from_provider"] == "anthropic" and fo["to_provider"] == "openai"
                    # second capture reuses the live session: no second session_started
                    # (flush the fake Redis first: the endpoint enforces a 5s cooldown between sends)
                    import asyncio
                    asyncio.run(server.app.state.redis.flushdb())
                    r = client.post("/api/text-capture", json={"text": "and a set?"},
                                    headers={"Authorization": f"Bearer {u.api_token}"})
                    assert r.status_code == 200, r.text
                    assert len(s.events("session_started")) == 1
            finally:
                server.async_client.messages.stream = orig_stream
                server.openai_async_client.chat.completions.create = orig_openai
        finally:
            cleanup(db, u)

    # -- 11. the browser half: identify vs reset in the rendered snippet ------------------
    def test_snippet_identifies_signed_in_and_resets_anonymous():
        import server
        db = SessionLocal()
        try:
            u = make_user(db, AccountLevel.trial)
            server.templates.env.globals["POSTHOG_KEY"] = "phc_test_only"
            try:
                r = client.get("/pricing", cookies={"session": create_token(u.id)})
                assert r.status_code == 200
                assert f'ph.identify("{u.id}"' in r.text
                assert "ph.reset()" not in r.text
                assert 'maskTextSelector: "#analysis, #transcription-box, #screenshot-wrap"' in r.text
                assert 'data-categories="analytics"' in r.text

                client.cookies.clear()
                r = client.get("/pricing")
                assert r.status_code == 200
                assert "ph.reset()" in r.text
                assert "ph.identify(" not in r.text
            finally:
                server.templates.env.globals["POSTHOG_KEY"] = ""
            # key unset (the local-dev default): no snippet at all
            r = client.get("/pricing")
            assert "posthog.init(" not in r.text
        finally:
            cleanup(db, u)

    def test_attribution_set_once_shape():
        once = analytics.attribution_set_once({"utm_source": "x", "r": "not a url", "t": "1"}, "google")
        assert once["signup_method"] == "google" and once["$initial_utm_source"] == "x"
        assert once["$initial_referrer"] == "not a url"
        assert once["$initial_referring_domain"] == "$direct"
        assert "t" not in once
        assert analytics.attribution_set_once(None, "github")["signup_method"] == "github"

    test("Suite never sends to PostHog (TESTING guard + blank key)", test_suite_never_sends_to_posthog)
    test("track(None) without a browser cookie is dropped", test_track_without_user_or_cookie_is_dropped)
    test("Browser $session_id attached to server events from the posthog-js cookie", test_session_id_attached_from_cookie)
    test("Stale $session_id (>30min) is not attached", test_stale_session_id_not_attached)
    test("Malformed posthog-js cookie is ignored", test_malformed_cookie_is_ignored)
    test("Anonymous contact_submitted lands on the browser id without a person profile", test_anonymous_contact_uses_browser_distinct_id)
    test("login_failed carries reason and user/anon id", test_login_failed_reasons)
    test("extension_connected fires exactly once and stamps ext_first_seen_at", test_extension_connected_once)
    test("/claim aliases the phone id and writes $initial_* attribution", test_claim_writes_attribution_and_aliases_phone_id)
    test("/auth/register writes attribution from ia_attr cookie", test_register_writes_attribution_from_cookie)
    test("subscription_created only on activation; updated/lapsed otherwise; profile refreshed", test_subscription_created_fires_only_on_activation)
    test("invoice.paid → first_invoice_paid once, then renewed", test_invoice_paid_events)
    test("/extension/uninstalled tracks server-side when signed in, client-side otherwise", test_extension_uninstalled_anonymous_vs_signed_in)
    test("Paid text capture fires session_started once and ai_failover", test_session_started_and_ai_failover_on_text_capture)
    test("Snippet identifies signed-in users and resets anonymous renders", test_snippet_identifies_signed_in_and_resets_anonymous)
    test("attribution_set_once builds $initial_* properties", test_attribution_set_once_shape)
