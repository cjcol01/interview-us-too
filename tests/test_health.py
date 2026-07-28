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
    test("GET /admin/health/deep/routes: returns route list",      test_deep_check_routes_endpoint)
    test("GET /healthz: public liveness check",                    test_healthz_public_no_auth)
