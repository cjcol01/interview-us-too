"""Send one of every email type to a test address for visual review.

Usage:
    python scripts/send_all_emails.py
    python scripts/send_all_emails.py other@example.com
"""
import sys
import os

# Run from repo root so config/mailer imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from config import NOTIFY_EMAIL
import mailer

TO = sys.argv[1] if len(sys.argv) > 1 else NOTIFY_EMAIL

print(f"Sending all email types to {TO} …\n")

emails = [
    ("Verification",           lambda: mailer.send_verification_email(TO, "preview-token-abc123")),
    ("Password reset",         lambda: mailer.send_password_reset_email(TO, "preview-token-xyz789")),
    ("Install link",           lambda: mailer.send_install_link_email(TO, "preview-token-install")),
    ("Desktop sign-in",        lambda: mailer.send_desktop_login_email(TO, "preview-token-login")),
    ("Password set",           lambda: mailer.send_password_set_email(TO)),
    ("Usage warning",          lambda: mailer.send_usage_warning_email(TO)),
    ("Account banned",         lambda: mailer.send_account_banned_email(TO)),
    ("Account unbanned",       lambda: mailer.send_account_unbanned_email(TO)),
    ("Subscription paused",    lambda: mailer.send_subscription_paused_email(TO)),
    ("Subscription resumed",   lambda: mailer.send_subscription_resumed_email(TO)),
    ("Expiry reminder",        lambda: mailer.send_expiry_reminder_email(TO, "31 Aug 2026")),
    ("Low sessions (1 left)",  lambda: mailer.send_low_sessions_email(TO, 1)),
    ("Interview reminder",     lambda: mailer.send_interview_reminder_email(TO, "CJ Coleman")),
    ("Announcement",           lambda: mailer.send_announcement_email(TO, "A note from the team", "We've just shipped a big update to InterviewWise.\n\nNew: instant replay now works on all tabs, not just Meet and Zoom.")),
    ("Lead announcement",      lambda: mailer.send_lead_announcement_email(TO, "Your free trial is waiting", "Hey — you signed up for InterviewWise but never finished setting up the extension.\n\nTook less than 60 seconds last time I checked.", "preview-lead-token")),
    # Internal / operator emails (go to NOTIFY_EMAIL regardless of TO)
    ("Cancel feedback — kept",      lambda: mailer.send_cancel_feedback_email(TO, "too_expensive", "I'd come back if it were cheaper", kept=True)),
    ("Cancel feedback — cancelled", lambda: mailer.send_cancel_feedback_email(TO, "not_used_enough", "", kept=False)),
    ("Account deletion",            lambda: mailer.send_account_deletion_email(TO, "got_job", "Got the offer! Thanks for the help.")),
    ("Contact form",                lambda: mailer.send_contact_email("support", TO, "Extension not connecting", "I installed the extension but the dashboard says disconnected. I've tried reinstalling.")),
    ("Webstore alert — DOWN",       lambda: mailer.send_webstore_alert_email("HTTP 404 from CRX update endpoint after 2 consecutive checks", recovered=False)),
    ("Webstore alert — recovered",  lambda: mailer.send_webstore_alert_email("CRX endpoint returned 200 and valid XML", recovered=True)),
]

ok = 0
for name, fn in emails:
    try:
        fn()
        print(f"  ✓  {name}")
        ok += 1
    except Exception as e:
        print(f"  ✗  {name}: {e}")

print(f"\n{ok}/{len(emails)} sent.")
