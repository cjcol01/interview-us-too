"""Resend-failure counter (metrics.py + its mailer.py wiring), feeding the "Resend
failures" row in the /admin/health "Metrics" section (see tests/test_health.py for the
5xx counter and the section as a whole).

record_email_failure() no-ops under TESTING=1 — it deliberately avoids opening a real
sync Redis connection during the test run (the app itself talks to fakeredis via the
async client, which a plain `redis.Redis.from_url(...)` can't see). So what's actually
verified here is the wiring: every mailer.py send function calls record_email_failure()
exactly when its Resend call raises, and never when it succeeds.
"""
from unittest.mock import patch


def register(test, skip, client=None):

    def test_record_email_failure_noops_under_testing():
        import metrics
        # Must not raise even though TESTING=1 means there's no real Redis to talk to.
        metrics.record_email_failure()

    def test_verification_email_failure_records_metric():
        import mailer
        with patch("mailer.resend.Emails.send", side_effect=RuntimeError("boom")), \
             patch("mailer.record_email_failure") as rec, \
             patch("mailer.RESEND_API_KEY", "re_live_fake_key_for_test"):
            mailer.send_verification_email("someone@example.com", "tok123")
        rec.assert_called_once()

    def test_low_sessions_email_failure_records_metric():
        import mailer
        with patch("mailer.resend.Emails.send", side_effect=RuntimeError("boom")), \
             patch("mailer.record_email_failure") as rec, \
             patch("mailer.RESEND_API_KEY", "re_live_fake_key_for_test"):
            mailer.send_low_sessions_email("someone@example.com", 1)
        rec.assert_called_once()

    def test_verification_email_success_does_not_record_metric():
        import mailer
        with patch("mailer.resend.Emails.send", return_value={"id": "abc"}), \
             patch("mailer.record_email_failure") as rec, \
             patch("mailer.RESEND_API_KEY", "re_live_fake_key_for_test"):
            mailer.send_verification_email("someone@example.com", "tok123")
        rec.assert_not_called()

    test("record_email_failure() no-ops under TESTING=1",         test_record_email_failure_noops_under_testing)
    test("send_verification_email failure records metric",        test_verification_email_failure_records_metric)
    test("send_low_sessions_email failure records metric",        test_low_sessions_email_failure_records_metric)
    test("send_verification_email success doesn't record metric", test_verification_email_success_does_not_record_metric)
