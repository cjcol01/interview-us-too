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
            ]:
                with patch(patch_target, return_value=fake_ok):
                    r = client.get(f"/admin/health/deep/{name}", cookies={"session": token})
                assert r.status_code == 200
                assert r.json() == fake_ok
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
    test("GET /admin/health/deep/{name} requires auth",            test_deep_check_endpoint_requires_auth)
    test("GET /admin/health/deep/{name}: unknown name → 404",      test_deep_check_endpoint_unknown_name_404)
    test("GET /admin/health/deep/{name}: returns one check result", test_deep_check_endpoint_returns_one_result_per_provider)
    test("GET /admin/health/deep/routes: returns route list",      test_deep_check_routes_endpoint)
    test("GET /healthz: public liveness check",                    test_healthz_public_no_auth)
