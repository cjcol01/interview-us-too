"""System health (`GET /admin/health`, `GET /healthz`) — the first is gated by
_require_author; /healthz is the public, unauthenticated liveness check meant for an
external monitor. Deep checks are fired one-per-request from `/admin/health/deep/{name}`
(the page calls each in parallel via JS so results render as they arrive, rather than
waiting for the slowest one) — we mock the underlying check functions here so the suite
stays fast and doesn't burn API quota on every run (the real calls are already exercised
by the "External APIs" section of run_tests.py).
"""
from unittest.mock import patch

from database import SessionLocal
from tests.helpers import cleanup
from tests.test_admin import _make_admin_cookie


def register(test, skip, client):

    def test_health_requires_auth():
        r = client.get("/admin/health")
        assert r.status_code == 401

    def test_health_success_renders():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin/health", cookies={"session": token})
            assert r.status_code == 200
            assert "System health" in r.text
            assert "Run deep checks" in r.text
        finally:
            cleanup(db, admin)
            db.close()

    def test_health_renders_metrics_section():
        """New 'Metrics' section (TODO.md 'Now' item): DB disk usage, billing summary,
        resend-failure / 5xx rolling-24h counters, and per-endpoint rate-limit activity."""
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin/health", cookies={"session": token})
            assert r.status_code == 200
            assert "Metrics" in r.text
            assert "DB disk usage" in r.text
            assert "Billing state" in r.text
            assert "Resend failures" in r.text
            assert "Error rate (5xx)" in r.text
            assert "capture" in r.text  # a rate-limited endpoint name from _RATE_LIMIT_ENDPOINTS
        finally:
            cleanup(db, admin)
            db.close()

    def test_sum_hourly_metric_counts_current_bucket():
        """_incr_hourly_metric/_sum_hourly_metric back the resend-failure and 5xx rows —
        verify a write in the current hour is picked up by the rolling 24h sum."""
        import asyncio
        from server import _incr_hourly_metric, _sum_hourly_metric
        from metrics import EMAIL_FAIL_PREFIX
        import server as _s

        async def _run():
            r = _s.app.state.redis
            before = await _sum_hourly_metric(r, EMAIL_FAIL_PREFIX)
            await _incr_hourly_metric(r, EMAIL_FAIL_PREFIX)
            after = await _sum_hourly_metric(r, EMAIL_FAIL_PREFIX)
            assert after == before + 1

        asyncio.run(_run())

    def test_5xx_response_increments_metric():
        """An unhandled exception inside a route re-raises through _request_logger (Starlette
        hoists the base-Exception handler to the outermost ServerErrorMiddleware, which always
        re-raises after building the 500 response — and TestClient's default
        raise_server_exceptions=True surfaces that same exception to the caller instead of a
        response object). _request_logger must still count it as a 5xx on the way past."""
        import asyncio
        from unittest.mock import patch
        from server import _sum_hourly_metric
        from metrics import HTTP_5XX_PREFIX
        import server as _s

        async def _sum():
            return await _sum_hourly_metric(_s.app.state.redis, HTTP_5XX_PREFIX)

        before = asyncio.run(_sum())
        with patch("server._check_redis", side_effect=RuntimeError("boom")):
            try:
                client.get("/healthz")
                assert False, "expected the exception to propagate to the test client"
            except RuntimeError:
                pass
        after = asyncio.run(_sum())
        assert after == before + 1

    def test_unhandled_exception_logs_query_string_and_user():
        """The query string disambiguates routes that serve several distinct UI actions off
        one path (e.g. /billing/checkout?plan=... covers both 'Top up sessions' and
        'Upgrade to Unlimited') — verify it lands in the logged message alongside the
        triggering user id, without needing to log request bodies (which for other routes
        could mean passwords or multi-MB screenshot/audio payloads)."""
        import asyncio
        from starlette.requests import Request
        from auth import create_token
        from database import SessionLocal
        from tests.helpers import cleanup, make_user
        from server import _unhandled_exception_handler

        db = SessionLocal()
        u = None
        try:
            u = make_user(db)
            token = create_token(u.id)
            scope = {
                "type": "http",
                "method": "GET",
                "path": "/billing/checkout",
                "query_string": b"plan=subscription",
                "headers": [(b"cookie", f"session={token}".encode())],
            }
            request = Request(scope)
            with patch("server.logger") as mock_logger:
                asyncio.run(_unhandled_exception_handler(request, RuntimeError("boom")))
            fmt, method, path, user_id = mock_logger.exception.call_args[0]
            assert method == "GET"
            assert path == "/billing/checkout?plan=subscription"
            assert user_id == u.id
        finally:
            cleanup(db, u)
            db.close()

    def test_recent_error_log_entries_captures_traceback():
        """'Recent errors' on /admin/health reads app.log back (see analytics.py's
        RotatingFileHandler) and groups traceback continuation lines with the ERROR header
        line that started them. Appends a fake entry directly to the test log file rather
        than triggering a real logger.exception() call — run_tests.py globally silences
        logging output (logging.disable(logging.CRITICAL)) to keep the suite's console
        quiet, so a real logger call wouldn't actually write anything during this run."""
        import os
        from database import DATA_DIR
        from server import _recent_error_log_entries, _LOG_FILENAME

        marker = "boom-for-log-test-xyz"
        log_path = os.path.join(DATA_DIR, _LOG_FILENAME)
        with open(log_path, "a") as f:
            f.write("2026-01-01 00:00:00 [ERROR] Unhandled exception on GET /whatever\n")
            f.write("Traceback (most recent call last):\n")
            f.write(f"RuntimeError: {marker}\n")

        entries = _recent_error_log_entries(max_entries=5)
        assert entries, "expected at least one ERROR entry"
        assert marker in entries[-1]
        assert "Traceback" in entries[-1]

    def test_health_renders_show_recent_errors_button():
        """The 'Recent errors' entries themselves are fetched on demand (see
        test_admin_health_logs_endpoint below), not rendered on every plain page load —
        only the toggle button appears in the initial page."""
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin/health", cookies={"session": token})
            assert r.status_code == 200
            assert "Show recent errors" in r.text
        finally:
            cleanup(db, admin)
            db.close()

    def test_admin_health_logs_requires_auth():
        r = client.get("/admin/health/logs")
        assert r.status_code == 401

    def test_admin_health_logs_endpoint():
        """GET /admin/health/logs backs the 'Show recent errors' button's fetch call."""
        import os
        from database import DATA_DIR
        from server import _LOG_FILENAME

        marker = "boom-for-log-endpoint-test"
        log_path = os.path.join(DATA_DIR, _LOG_FILENAME)
        with open(log_path, "a") as f:
            f.write("2026-01-01 00:00:00 [ERROR] Unhandled exception on POST /billing/checkout (user=42)\n")
            f.write("Traceback (most recent call last):\n")
            f.write(f"RuntimeError: {marker}\n")

        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin/health/logs", cookies={"session": token})
            assert r.status_code == 200
            body = r.json()
            assert "log_file_path" in body
            assert body["entries"], "expected at least one entry"
            assert marker in body["entries"][0]  # newest first
        finally:
            cleanup(db, admin)
            db.close()

    def test_recent_error_log_entries_since_filters_old_entries():
        """`since` backs the 'Clear errors' button — entries at/before the cutoff are
        dropped, entries after it survive."""
        import os
        from datetime import datetime
        from database import DATA_DIR
        from server import _recent_error_log_entries, _LOG_FILENAME

        old_marker = "boom-since-filter-old-xyz"
        new_marker = "boom-since-filter-new-xyz"
        log_path = os.path.join(DATA_DIR, _LOG_FILENAME)
        with open(log_path, "a") as f:
            f.write(f"2026-01-01 00:00:00 [ERROR] {old_marker}\n")
            f.write(f"2026-07-01 00:00:00 [ERROR] {new_marker}\n")

        entries = _recent_error_log_entries(max_entries=50, since=datetime(2026, 6, 1))
        joined = "\n".join(entries)
        assert old_marker not in joined
        assert new_marker in joined

    def test_admin_health_clear_errors_requires_auth():
        r = client.post("/admin/health/clear-errors")
        assert r.status_code == 401

    def test_admin_health_clear_errors_resets_counters():
        import asyncio
        from server import _sum_hourly_metric, _incr_hourly_metric
        from metrics import EMAIL_FAIL_PREFIX, HTTP_5XX_PREFIX
        import server as _s

        async def _bump():
            r = _s.app.state.redis
            await _incr_hourly_metric(r, EMAIL_FAIL_PREFIX)
            await _incr_hourly_metric(r, HTTP_5XX_PREFIX)
        asyncio.run(_bump())

        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.post("/admin/health/clear-errors", cookies={"session": token})
            assert r.status_code == 200

            async def _sums():
                rr = _s.app.state.redis
                return (
                    await _sum_hourly_metric(rr, EMAIL_FAIL_PREFIX),
                    await _sum_hourly_metric(rr, HTTP_5XX_PREFIX),
                )
            email_sum, http_sum = asyncio.run(_sums())
            assert email_sum == 0
            assert http_sum == 0
        finally:
            cleanup(db, admin)
            db.close()

    def test_admin_health_clear_errors_hides_old_log_entries_but_not_new_ones():
        import os
        from datetime import datetime
        from database import DATA_DIR
        from server import _LOG_FILENAME

        old_marker = "boom-before-clear-xyz"
        log_path = os.path.join(DATA_DIR, _LOG_FILENAME)
        with open(log_path, "a") as f:
            f.write("2026-01-01 00:00:00 [ERROR] Unhandled exception on GET /old\n")
            f.write(f"RuntimeError: {old_marker}\n")

        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.post("/admin/health/clear-errors", cookies={"session": token})
            assert r.status_code == 200

            new_marker = "boom-after-clear-xyz"
            now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            with open(log_path, "a") as f:
                f.write(f"{now_str} [ERROR] Unhandled exception on GET /new\n")
                f.write(f"RuntimeError: {new_marker}\n")

            r2 = client.get("/admin/health/logs", cookies={"session": token})
            assert r2.status_code == 200
            joined = "\n".join(r2.json()["entries"])
            assert new_marker in joined
            assert old_marker not in joined
        finally:
            cleanup(db, admin)
            db.close()

    def test_trigger_test_error_requires_auth():
        r = client.post("/admin/health/trigger-test-error")
        assert r.status_code == 401

    def test_trigger_test_error_increments_5xx_and_logs():
        """Deliberately raises — see test_5xx_response_increments_metric above for why
        TestClient surfaces this as a raised exception rather than a 500 response object."""
        import asyncio
        from server import _sum_hourly_metric, _TestErrorTrigger
        from metrics import HTTP_5XX_PREFIX
        import server as _s

        async def _sum():
            return await _sum_hourly_metric(_s.app.state.redis, HTTP_5XX_PREFIX)

        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            before = asyncio.run(_sum())
            try:
                client.post("/admin/health/trigger-test-error", cookies={"session": token})
                assert False, "expected the exception to propagate to the test client"
            except _TestErrorTrigger:
                pass
            after = asyncio.run(_sum())
            assert after == before + 1
        finally:
            cleanup(db, admin)
            db.close()

    def test_deep_check_endpoint_requires_auth():
        r = client.get("/admin/health/deep/anthropic")
        assert r.status_code == 401

    def test_deep_check_endpoint_unknown_name_404():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin/health/deep/not-a-real-check", cookies={"session": token})
            assert r.status_code == 404
        finally:
            cleanup(db, admin)
            db.close()

    def test_deep_check_endpoint_returns_one_result_per_provider():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            fake_ok = {"ok": True, "detail": "stub", "latency_ms": 1.0}
            for name, patch_target in [
                ("anthropic", "server._check_anthropic"),
                ("openai", "server._check_openai"),
                ("deepgram", "server._check_deepgram"),
                ("stripe", "server._check_stripe"),
                ("sideload", "server._check_sideload"),
            ]:
                with patch(patch_target, return_value=fake_ok):
                    r = client.get(f"/admin/health/deep/{name}", cookies={"session": token})
                assert r.status_code == 200
                assert r.json() == fake_ok
        finally:
            cleanup(db, admin)
            db.close()

    def test_check_sideload_disabled_returns_unknown():
        """When SIDELOAD_ENABLED is off, the check should say so rather than making a
        network call against a page that 404s by design — pin the flag rather than relying
        on the local .env, since deploys may enable it."""
        from server import _check_sideload
        with patch("server.SIDELOAD_ENABLED", False):
            result = _check_sideload()
        assert result["ok"] is None
        assert "disabled" in result["detail"]

    def test_check_sideload_reports_cdn_and_mirror_status():
        """When enabled, reports both the CDN and same-origin mirror HTTP status without
        hitting the real network — mocks requests.head."""
        from server import _check_sideload

        class _FakeResp:
            def __init__(self, status_code):
                self.status_code = status_code

        with patch("server.SIDELOAD_ENABLED", True), \
             patch("server.requests.head", return_value=_FakeResp(200)):
            result = _check_sideload()
        assert result["ok"] is True
        assert "200" in result["detail"]

    # --- Chrome Web Store listing watch --------------------------------------
    # _check_webstore reads Chrome's CRX update endpoint rather than the public listing
    # page, because that page returns HTTP 200 even for an ID that never existed. These
    # tests pin the three verdicts the alerts strip branches on: live / down / unknown.
    _WEBSTORE_OK_XML = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gupdate xmlns="http://www.google.com/update2/response" protocol="2.0">'
        '<app appid="abc" status="ok"><updatecheck status="ok" version="2.4.0"/></app></gupdate>'
    )
    _WEBSTORE_GONE_XML = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<gupdate xmlns="http://www.google.com/update2/response" protocol="2.0">'
        '<app appid="abc" status="error-unknownApplication"/></gupdate>'
    )

    class _FakeXmlResp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    def test_check_webstore_unconfigured_returns_neutral():
        """No extension ID means there's no listing to watch — say so rather than making a
        pointless request against an empty ID."""
        from server import _check_webstore
        with patch("server.WEBSTORE_EXTENSION_ID", ""):
            result = _check_webstore()
        assert result["ok"] is None
        assert result["state"] == "unconfigured"

    def test_check_webstore_published_reports_live_version():
        from server import _check_webstore
        with patch("server.WEBSTORE_EXTENSION_ID", "a" * 32), \
             patch("server.requests.get", return_value=_FakeXmlResp(_WEBSTORE_OK_XML)):
            result = _check_webstore()
        assert result["ok"] is True
        assert result["state"] == "live"
        assert "2.4.0" in result["detail"]

    def test_check_webstore_taken_down_reports_down():
        """The whole point of the check: error-unknownApplication means unpublished, removed
        or taken down, and must come back as a hard failure."""
        from server import _check_webstore
        with patch("server.WEBSTORE_EXTENSION_ID", "a" * 32), \
             patch("server.requests.get", return_value=_FakeXmlResp(_WEBSTORE_GONE_XML)):
            result = _check_webstore()
        assert result["ok"] is False
        assert result["state"] == "down"
        assert "error-unknownApplication" in result["detail"]

    def test_check_webstore_network_failure_is_unknown_not_down():
        """A network blip must not read as a takedown — otherwise the /admin danger alert
        cries wolf every time Google is briefly unreachable."""
        from server import _check_webstore
        with patch("server.WEBSTORE_EXTENSION_ID", "a" * 32), \
             patch("server.requests.get", side_effect=OSError("connection reset")):
            result = _check_webstore()
        assert result["state"] == "unknown"
        assert result["ok"] is None

    def test_webstore_version_drift_noted_but_not_a_failure():
        """A store version behind the local manifest is normal mid-review, so it annotates
        the row instead of failing it."""
        from server import _check_webstore
        with patch("server.WEBSTORE_EXTENSION_ID", "a" * 32), \
             patch("server._local_extension_version", return_value="9.9.9"), \
             patch("server.requests.get", return_value=_FakeXmlResp(_WEBSTORE_OK_XML)):
            result = _check_webstore()
        assert result["ok"] is True
        assert "9.9.9" in result["detail"]

    # --- Takedown alert email (edge-triggered) --------------------------------
    # Every test here drives _handle_webstore_transition directly and asserts on the mocked
    # mailer, so no real email is ever sent even though the suite has a live Resend key.
    def _drive_webstore_states(states):
        """Feeds a sequence of states through the transition handler against a clean Redis,
        returning the list of (detail, recovered) email calls it made."""
        import asyncio
        import server

        async def _run():
            r = server.app.state.redis
            await r.delete(server._WEBSTORE_DOWN_STREAK_KEY, server._WEBSTORE_ALERTED_KEY)
            with patch("server.send_webstore_alert_email") as mock_send:
                for state in states:
                    await server._handle_webstore_transition(r, {"state": state, "detail": state})
                return mock_send.call_args_list

        return asyncio.run(_run())

    def test_single_down_reading_does_not_email():
        """One 'down' is unconfirmed — Google having a bad moment must not fire an alarming
        takedown email."""
        calls = _drive_webstore_states(["down"])
        assert calls == []

    def test_two_consecutive_down_readings_email_once():
        """Confirmed down alerts — and stays quiet on every subsequent tick of the same
        outage rather than emailing every 30 minutes until it's fixed."""
        calls = _drive_webstore_states(["down", "down", "down", "down"])
        assert len(calls) == 1
        assert calls[0].args[0] == "down"

    def test_unknown_does_not_reset_the_down_streak():
        """An unreachable-Google reading between two 'down' readings must not clear the
        streak, or a flaky network could stop the alert from ever confirming."""
        calls = _drive_webstore_states(["down", "unknown", "down"])
        assert len(calls) == 1

    def test_live_reading_clears_streak_without_emailing():
        """Recovering before the alert ever fired means nothing to report."""
        calls = _drive_webstore_states(["down", "live", "down"])
        assert calls == []

    def test_recovery_after_alert_sends_all_clear():
        calls = _drive_webstore_states(["down", "down", "live"])
        assert len(calls) == 2
        assert calls[1].args[1] is True  # recovered=True

    def test_deep_check_does_not_send_alert_email():
        """Clicking the deep check refreshes the cache but must never email — you're already
        looking at the result."""
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            down = {"ok": False, "state": "down", "detail": "gone", "latency_ms": 1.0}
            with patch("server.WEBSTORE_EXTENSION_ID", "a" * 32), \
                 patch("server._check_webstore", return_value=down), \
                 patch("server.send_webstore_alert_email") as mock_send:
                r = client.get("/admin/health/deep/webstore", cookies={"session": token})
                assert r.status_code == 200
                assert mock_send.call_count == 0
        finally:
            cleanup(db, admin)
            db.close()

    def test_deep_webstore_endpoint_caches_verdict_for_admin_alerts():
        """Clicking the deep check must also refresh the cached verdict, since /admin's
        alerts strip only ever reads the cache (it makes no outbound calls)."""
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            down = {"ok": False, "state": "down", "detail": "listing unavailable", "latency_ms": 5.0}
            # The ID has to be pinned for both calls: unset, the cached-status helper reports
            # "unconfigured" and never looks at Redis at all.
            with patch("server.WEBSTORE_EXTENSION_ID", "a" * 32):
                with patch("server._check_webstore", return_value=down):
                    r = client.get("/admin/health/deep/webstore", cookies={"session": token})
                assert r.status_code == 200
                assert r.json()["state"] == "down"
                # Cache now populated, so /admin surfaces the danger alert with no network call.
                r = client.get("/admin", cookies={"session": token})
            assert r.status_code == 200
            assert "Chrome Web Store listing is down" in r.text
        finally:
            cleanup(db, admin)
            db.close()

    def test_health_page_shows_webstore_row():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            r = client.get("/admin/health", cookies={"session": token})
            assert r.status_code == 200
            assert "Chrome Web Store listing" in r.text
        finally:
            cleanup(db, admin)
            db.close()

    def test_deep_check_routes_endpoint():
        db = SessionLocal()
        admin = None
        try:
            admin, token = _make_admin_cookie(db)
            fake_routes = [{"name": "/", "ok": True, "detail": "HTTP 200", "latency_ms": 1.0}]
            with patch("server._check_routes", return_value=fake_routes):
                r = client.get("/admin/health/deep/routes", cookies={"session": token})
            assert r.status_code == 200
            assert r.json() == {"routes": fake_routes}
        finally:
            cleanup(db, admin)
            db.close()

    def test_healthz_public_no_auth():
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["redis"] is True
        assert body["database"] is True

    test("GET /admin/health requires auth",                       test_health_requires_auth)
    test("GET /admin/health: success renders",                     test_health_success_renders)
    test("GET /admin/health: renders Metrics section",             test_health_renders_metrics_section)
    test("_sum_hourly_metric counts current-hour bucket",          test_sum_hourly_metric_counts_current_bucket)
    test("A 500 response increments the rolling 5xx metric",       test_5xx_response_increments_metric)
    test("Unhandled exception logs query string + user id",        test_unhandled_exception_logs_query_string_and_user)
    test("_recent_error_log_entries captures a traceback",         test_recent_error_log_entries_captures_traceback)
    test("GET /admin/health: renders 'Show recent errors' button", test_health_renders_show_recent_errors_button)
    test("GET /admin/health/logs requires auth",                   test_admin_health_logs_requires_auth)
    test("GET /admin/health/logs: returns recent ERROR entries",   test_admin_health_logs_endpoint)
    test("_recent_error_log_entries: since filters old entries",   test_recent_error_log_entries_since_filters_old_entries)
    test("POST /admin/health/clear-errors requires auth",          test_admin_health_clear_errors_requires_auth)
    test("POST /admin/health/clear-errors resets counters",        test_admin_health_clear_errors_resets_counters)
    test("Clear errors hides old log entries, keeps new ones",     test_admin_health_clear_errors_hides_old_log_entries_but_not_new_ones)
    test("POST /admin/health/trigger-test-error requires auth",    test_trigger_test_error_requires_auth)
    test("Trigger test error increments 5xx + logs",               test_trigger_test_error_increments_5xx_and_logs)
    test("GET /admin/health/deep/{name} requires auth",            test_deep_check_endpoint_requires_auth)
    test("GET /admin/health/deep/{name}: unknown name → 404",      test_deep_check_endpoint_unknown_name_404)
    test("GET /admin/health/deep/{name}: returns one check result", test_deep_check_endpoint_returns_one_result_per_provider)
    test("_check_sideload: disabled → unknown/neutral",            test_check_sideload_disabled_returns_unknown)
    test("_check_sideload: enabled → reports CDN + mirror status",  test_check_sideload_reports_cdn_and_mirror_status)
    test("_check_webstore: no extension ID → neutral",             test_check_webstore_unconfigured_returns_neutral)
    test("_check_webstore: published → live + version",            test_check_webstore_published_reports_live_version)
    test("_check_webstore: taken down → hard failure",             test_check_webstore_taken_down_reports_down)
    test("_check_webstore: network error → unknown, not down",     test_check_webstore_network_failure_is_unknown_not_down)
    test("_check_webstore: version drift noted, not failed",       test_webstore_version_drift_noted_but_not_a_failure)
    test("Webstore: one down reading does not email",              test_single_down_reading_does_not_email)
    test("Webstore: confirmed down emails exactly once",           test_two_consecutive_down_readings_email_once)
    test("Webstore: 'unknown' does not reset the down streak",     test_unknown_does_not_reset_the_down_streak)
    test("Webstore: recovery before alert stays silent",           test_live_reading_clears_streak_without_emailing)
    test("Webstore: recovery after alert sends all-clear",         test_recovery_after_alert_sends_all_clear)
    test("Webstore: deep check never sends an alert email",        test_deep_check_does_not_send_alert_email)
    test("Deep webstore check caches verdict → /admin alert",      test_deep_webstore_endpoint_caches_verdict_for_admin_alerts)
    test("GET /admin/health: renders Web Store listing row",       test_health_page_shows_webstore_row)
    test("GET /admin/health/deep/routes: returns route list",      test_deep_check_routes_endpoint)
    test("GET /healthz: public liveness check",                    test_healthz_public_no_auth)
