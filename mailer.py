import resend

from analytics import logger
from config import BASE_URL, FROM_EMAIL, NOTIFY_EMAIL, RESEND_API_KEY
from metrics import record_email_failure

resend.api_key = RESEND_API_KEY

_PLACEHOLDER = "re_xxxxxxxxxxxx"


def send_verification_email(to_email: str, token: str) -> None:
    url = f"{BASE_URL}/verify?token={token}"
    logger.info("[email] verify link for %s: %s", to_email, url)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Confirm your email to start your free InterviewAce trial",
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;">Welcome to InterviewAce 👋</h2>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                Tap the button below to confirm your email and unlock your free 10-minute trial.
              </p>
              <a href="{url}" style="display:inline-block;background:#6c63ff;color:#ffffff;
                 border-radius:8px;padding:12px 24px;text-decoration:none;font-weight:600;">
                Confirm my email
              </a>
              <p style="margin:24px 0 0;color:#8a8a9a;font-size:0.82rem;line-height:1.6;">
                Or copy this link into your browser:<br>{url}
              </p>
              <p style="margin:24px 0 0;color:#a0a0b0;font-size:0.78rem;line-height:1.6;border-top:1px solid #eee;padding-top:16px;">
                If you didn't sign up for InterviewAce, you can safely ignore this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send via Resend: %s", e)
        record_email_failure()


def send_password_reset_email(to_email: str, token: str) -> None:
    url = f"{BASE_URL}/reset-password?token={token}"
    logger.info("[email] password-reset link for %s: %s", to_email, url)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Reset your InterviewAce password",
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;">Reset your password</h2>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                Click the button below to set a new password. This link expires in 1 hour.
              </p>
              <a href="{url}" style="display:inline-block;background:#6c63ff;color:#ffffff;
                 border-radius:8px;padding:12px 24px;text-decoration:none;font-weight:600;">
                Reset my password
              </a>
              <p style="margin:24px 0 0;color:#8a8a9a;font-size:0.82rem;line-height:1.6;">
                Or copy this link into your browser:<br>{url}
              </p>
              <p style="margin:24px 0 0;color:#a0a0b0;font-size:0.78rem;line-height:1.6;border-top:1px solid #eee;padding-top:16px;">
                If you didn't request a password reset, you can safely ignore this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send reset email: %s", e)
        record_email_failure()


_REASON_LABELS = {
    "got_job":         "I got the job!",
    "too_expensive":   "Too expensive",
    "not_used_enough": "Didn't use it enough",
    "had_issues":      "It was buggy / I had issues",
    "missing_feature": "Missing a feature",
    "privacy":         "Privacy / data concerns",
    "other":           "Other",
}


def send_cancel_feedback_email(user_email: str, reason: str, detail: str, kept: bool) -> None:
    action = "stayed" if kept else "cancelled"
    reason_label = _REASON_LABELS.get(reason, reason or "—")
    detail_block = (
        f'<p style="margin:12px 0 0;padding:12px;background:#1a1a2e;border-radius:8px;'
        f'color:#ccc;font-size:0.9rem;line-height:1.6;">{detail}</p>'
        if detail else
        '<p style="margin:12px 0 0;color:#555;font-size:0.85rem;">No additional detail.</p>'
    )

    logger.info("[cancel-feedback] user=%s action=%s reason=%s", user_email, action, reason_label)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": NOTIFY_EMAIL,
            "subject": f"[InterviewAce] Cancel feedback — {reason_label} ({action})",
            "html": f"""
            <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;
                        padding:32px;background:#0d0d0d;color:#e0e0e0;">
              <h2 style="margin:0 0 4px;color:#fff;font-size:1.1rem;">Cancel page feedback</h2>
              <p style="margin:0 0 24px;color:#555;font-size:0.82rem;">
                from <strong style="color:#888;">{user_email}</strong>
              </p>

              <table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
                <tr>
                  <td style="padding:10px 0;color:#666;width:110px;">Outcome</td>
                  <td style="padding:10px 0;color:{'#00d4aa' if kept else '#f87171'};font-weight:600;">
                    {'Kept subscription' if kept else 'Cancelled'}
                  </td>
                </tr>
                <tr style="border-top:1px solid #1e1e2e;">
                  <td style="padding:10px 0;color:#666;">Reason</td>
                  <td style="padding:10px 0;color:#e0e0e0;font-weight:600;">{reason_label}</td>
                </tr>
              </table>

              <p style="margin:16px 0 4px;color:#666;font-size:0.82rem;">Detail</p>
              {detail_block}
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send cancel feedback: %s", e)
        record_email_failure()


def send_usage_warning_email(to_email: str) -> None:
    logger.info("[email] usage warning sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Unusual activity on your InterviewAce account",
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;">We've noticed unusual activity</h2>
              <p style="margin:0 0 16px;color:#4a4a5e;line-height:1.6;">
                Your account has been sending far more requests than a typical interview session
                involves. This is a heads-up that we've flagged it for review.
              </p>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                If this was you and there's a good reason for it, no action is needed. If it
                continues, we may pause or restrict access to keep the service fair for everyone.
              </p>
              <p style="margin:24px 0 0;color:#a0a0b0;font-size:0.78rem;line-height:1.6;border-top:1px solid #eee;padding-top:16px;">
                Questions? Just reply to this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send usage warning: %s", e)
        record_email_failure()


def send_account_banned_email(to_email: str) -> None:
    logger.info("[email] ban notice sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewAce account has been suspended",
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;">Your account has been suspended</h2>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                We've suspended access to your InterviewAce account. You won't be able to log in
                or use the extension while it's suspended.
              </p>
              <p style="margin:24px 0 0;color:#a0a0b0;font-size:0.78rem;line-height:1.6;border-top:1px solid #eee;padding-top:16px;">
                If you think this is a mistake, just reply to this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send ban notice: %s", e)
        record_email_failure()


def send_account_unbanned_email(to_email: str) -> None:
    logger.info("[email] unban notice sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewAce account has been restored",
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;">Your account has been restored</h2>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                Your InterviewAce account is no longer suspended. You can log in and use the
                extension again as normal.
              </p>
              <p style="margin:24px 0 0;color:#a0a0b0;font-size:0.78rem;line-height:1.6;border-top:1px solid #eee;padding-top:16px;">
                Questions? Just reply to this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send unban notice: %s", e)
        record_email_failure()


def send_subscription_paused_email(to_email: str) -> None:
    logger.info("[email] subscription-paused notice sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewAce subscription has been paused",
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;">Your subscription has been paused</h2>
              <p style="margin:0 0 16px;color:#4a4a5e;line-height:1.6;">
                We've paused your InterviewAce subscription. Billing has stopped and your plan has
                been downgraded for now.
              </p>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                If you think this is a mistake, just reply to this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send subscription-paused notice: %s", e)
        record_email_failure()


def send_subscription_resumed_email(to_email: str) -> None:
    logger.info("[email] subscription-resumed notice sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewAce subscription has been resumed",
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;">Your subscription has been resumed</h2>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                Your InterviewAce subscription is active again and billing has resumed as normal.
              </p>
              <p style="margin:24px 0 0;color:#a0a0b0;font-size:0.78rem;line-height:1.6;border-top:1px solid #eee;padding-top:16px;">
                Questions? Just reply to this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send subscription-resumed notice: %s", e)
        record_email_failure()


def send_expiry_reminder_email(to_email: str, cancel_date: str) -> None:
    logger.info("[email] expiry reminder sent to %s (ends %s)", to_email, cancel_date)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewAce access ends soon",
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;">Your access ends on {cancel_date}</h2>
              <p style="margin:0 0 16px;color:#4a4a5e;line-height:1.6;">
                Your InterviewAce subscription is set to cancel on {cancel_date}. You'll keep full
                access until then, and can undo this any time before that date from your account
                settings.
              </p>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                <a href="{BASE_URL}/settings" style="color:#1a1a2e;">Manage your subscription</a>
              </p>
              <p style="margin:24px 0 0;color:#a0a0b0;font-size:0.78rem;line-height:1.6;border-top:1px solid #eee;padding-top:16px;">
                Questions? Just reply to this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send expiry reminder: %s", e)
        record_email_failure()


def send_low_sessions_email(to_email: str, sessions_remaining: int) -> None:
    logger.info("[email] low-sessions notice sent to %s (%d left)", to_email, sessions_remaining)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    plural = "session" if sessions_remaining == 1 else "sessions"
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": f"{sessions_remaining} {plural} left on your InterviewAce account",
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;">You have {sessions_remaining} {plural} left</h2>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                Once they're used up you'll need to top up before starting another interview session.
              </p>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                <a href="{BASE_URL}/pricing" style="color:#1a1a2e;">Top up sessions</a>
              </p>
              <p style="margin:24px 0 0;color:#a0a0b0;font-size:0.78rem;line-height:1.6;border-top:1px solid #eee;padding-top:16px;">
                Questions? Just reply to this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send low-sessions notice: %s", e)
        record_email_failure()


def send_interview_reminder_email(to_email: str, full_name: str) -> None:
    logger.info("[email] interview reminder sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    first_name = (full_name or "").split(" ")[0] or "there"
    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your interview is tomorrow",
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <h2 style="margin:0 0 16px;color:#1a1a2e;">Good luck tomorrow, {first_name}</h2>
              <p style="margin:0 0 16px;color:#4a4a5e;line-height:1.6;">
                Quick setup check before you go in: make sure the extension is installed, connected,
                and your phone or second device is signed in and propped up where you can glance at it.
              </p>
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">
                <a href="{BASE_URL}/settings" style="color:#1a1a2e;">Check your setup</a>
              </p>
              <p style="margin:24px 0 0;color:#a0a0b0;font-size:0.78rem;line-height:1.6;border-top:1px solid #eee;padding-top:16px;">
                This is the only reminder you'll get from us about this interview. Questions? Just reply to this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send interview reminder: %s", e)
        record_email_failure()


def send_announcement_email(to_email: str, subject: str, body: str) -> None:
    """Admin-authored announcement — body is plain text, wrapped in the standard shell.
    Newlines are preserved as line breaks; no other formatting is assumed."""
    logger.info("[email] announcement %r sent to %s", subject, to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    from html import escape
    body_html = escape(body).replace("\n", "<br>")

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "html": f"""
            <div style="font-family:system-ui,-apple-system,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#ffffff;color:#1a1a2e;">
              <p style="margin:0 0 24px;color:#4a4a5e;line-height:1.6;">{body_html}</p>
              <p style="margin:24px 0 0;color:#a0a0b0;font-size:0.78rem;line-height:1.6;border-top:1px solid #eee;padding-top:16px;">
                Questions? Just reply to this email.
              </p>
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send announcement to %s: %s", to_email, e)
        record_email_failure()


def send_account_deletion_email(user_email: str, reason: str, detail: str) -> None:
    reason_label = _REASON_LABELS.get(reason, reason or "—")
    detail_block = (
        f'<p style="margin:12px 0 0;padding:12px;background:#1a1a2e;border-radius:8px;'
        f'color:#ccc;font-size:0.9rem;line-height:1.6;">{detail}</p>'
        if detail else
        '<p style="margin:12px 0 0;color:#555;font-size:0.85rem;">No additional detail.</p>'
    )

    logger.info("[account-delete] user=%s reason=%s", user_email, reason_label)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": NOTIFY_EMAIL,
            "subject": f"[InterviewAce] Account deleted — {reason_label}",
            "html": f"""
            <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;
                        padding:32px;background:#0d0d0d;color:#e0e0e0;">
              <h2 style="margin:0 0 4px;color:#fff;font-size:1.1rem;">Account deletion</h2>
              <p style="margin:0 0 24px;color:#555;font-size:0.82rem;">
                from <strong style="color:#888;">{user_email}</strong>
              </p>

              <table style="width:100%;border-collapse:collapse;font-size:0.9rem;">
                <tr>
                  <td style="padding:10px 0;color:#666;width:110px;">Reason</td>
                  <td style="padding:10px 0;color:#e0e0e0;font-weight:600;">{reason_label}</td>
                </tr>
              </table>

              <p style="margin:16px 0 4px;color:#666;font-size:0.82rem;">Detail</p>
              {detail_block}
            </div>
            """,
        })
    except Exception as e:
        logger.error("[email] failed to send account deletion notice: %s", e)
        record_email_failure()
