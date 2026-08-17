import urllib.parse

import resend

from analytics import logger
from config import BASE_URL, COMPANY_ADDRESS, FROM_EMAIL, NOTIFY_EMAIL, RESEND_API_KEY
from metrics import record_email_failure

resend.api_key = RESEND_API_KEY

_PLACEHOLDER = "re_xxxxxxxxxxxx"


# ---------------------------------------------------------------------------
# Template primitives
# ---------------------------------------------------------------------------

def _p(text: str, small: bool = False, last: bool = False) -> str:
    """A styled paragraph for inside the card.

    small=True  → 13 px muted helper text (used for URL fallbacks / caveats).
    last=True   → removes the bottom margin so the card padding is the only gap.
    """
    if small:
        return (
            '<p style="margin:16px 0 0;font-family:Helvetica,Arial,sans-serif;'
            'font-size:13px;line-height:20px;mso-line-height-rule:exactly;'
            f'color:#9A9A94;">{text}</p>'
        )
    bottom = "0" if last else "20px"
    return (
        f'<p style="margin:0 0 {bottom};font-family:Helvetica,Arial,sans-serif;'
        'font-size:16px;line-height:26px;mso-line-height-rule:exactly;'
        f'color:#5C5C58;">{text}</p>'
    )


def _cta(label: str, url: str) -> str:
    """Bulletproof CTA button — bgcolor on the <td> so Outlook renders it filled."""
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="margin:4px 0 0;"><tr>'
        '<td bgcolor="#C6F24E" style="background-color:#C6F24E;border-radius:10px;text-align:center;">'
        f'<a href="{url}" style="display:block;padding:15px 24px;'
        'font-family:Helvetica,Arial,sans-serif;font-size:15px;font-weight:700;'
        'color:#1A2A05;text-decoration:none;mso-line-height-rule:exactly;line-height:22px;">'
        f'{label}</a>'
        '</td></tr></table>'
    )


def _field(label: str, value: str) -> str:
    """A label/value row for structured data inside the card (e.g. 'Outcome · Cancelled').
    Adds a hairline divider above itself; stack several to build a data table."""
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="border-top:1px solid #F0EFEC;margin:0;">'
        '<tr>'
        f'<td style="padding:10px 0;font-family:Helvetica,Arial,sans-serif;font-size:13px;'
        'line-height:18px;color:#9A9A94;width:110px;vertical-align:top;">'
        f'{label}</td>'
        f'<td style="padding:10px 0;font-family:Helvetica,Arial,sans-serif;font-size:13px;'
        'line-height:18px;color:#161614;font-weight:600;vertical-align:top;">'
        f'{value}</td>'
        '</tr></table>'
    )


def _block(text: str) -> str:
    """A muted inset block for free-form text (messages, detail notes)."""
    return (
        '<p style="margin:16px 0 0;padding:14px 16px;background:#F7F6F3;border-radius:8px;'
        'font-family:Helvetica,Arial,sans-serif;font-size:14px;line-height:22px;'
        f'color:#5C5C58;">{text}</p>'
    )


def _url_fallback(url: str) -> str:
    """Small 'can't click the button? copy this' text, placed after a CTA."""
    return _p(
        'Or copy this link into your browser:<br />'
        f'<a href="{url}" style="color:#9A9A94;word-break:break-all;">{url}</a>',
        small=True,
    )


def _email_html(
    preheader: str,
    kicker_num: str,
    kicker_label: str,
    headline: str,
    body_html: str,
    note_line: str = "",
    show_unsubscribe: bool = False,
    unsubscribe_label: str = "Unsubscribe",
    unsubscribe_url: str = "",
) -> str:
    """Render the complete branded email shell around card body HTML.

    Content slots
    -------------
    preheader       ~85-char preview text (hidden from body, shown in inbox list).
    kicker_num      Two-digit string, e.g. "01".
    kicker_label    Short uppercase label, e.g. "Get started".  CSS does the caps.
    headline        Sentence-case headline, aim for ≤40 chars.
    body_html       Pre-built HTML for the card body (below h1).  Use _p/_cta helpers.
    note_line       Optional HTML shown centred below the card (plain reassurance text).
    show_unsubscribe  Add an unsubscribe link to the footer (lifecycle emails only).
    """
    addr = f"InterviewWise · {COMPANY_ADDRESS}" if COMPANY_ADDRESS else "InterviewWise"

    unsub = ""
    if show_unsubscribe and unsubscribe_url:
        unsub = (
            f'<br /><a href="{unsubscribe_url}" '
            'style="color:#9A9A94;text-decoration:underline;">'
            f'{unsubscribe_label}</a>'
        )

    note_row = ""
    if note_line:
        note_row = (
            "          <tr>\n"
            '            <td align="center" style="padding:20px 0 0;">\n'
            '              <p style="margin:0;font-family:Helvetica,Arial,sans-serif;'
            "font-size:13px;line-height:22px;mso-line-height-rule:exactly;"
            f'color:#6E6E68;text-align:center;">{note_line}</p>\n'
            "            </td>\n"
            "          </tr>\n"
        )

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <meta name="color-scheme" content="light dark" />
  <meta name="supported-color-schemes" content="light dark" />
  <title></title>
  <!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
  <style>
    @media only screen and (max-width:480px) {{
      .op {{ padding-left:16px !important; padding-right:16px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#F3F2EE;">

  <span style="display:none;font-size:0;line-height:0;max-height:0;overflow:hidden;mso-hide:all;">{preheader}</span>

  <table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#F3F2EE" style="background-color:#F3F2EE;">
    <tr>
      <td align="center" class="op" style="padding:32px 30px 0;">
        <table width="600" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;width:100%;">

          <!-- Wordmark -->
          <tr>
            <td align="center" style="padding-bottom:26px;">
              <span style="font-family:Helvetica,Arial,sans-serif;font-size:15px;font-weight:700;letter-spacing:-0.01em;line-height:1;"><span style="color:#5C5C58;">Interview</span><span style="color:#161614;">Wise</span></span>
            </td>
          </tr>

          <!-- Card -->
          <tr>
            <td bgcolor="#FFFFFF" style="background-color:#FFFFFF;border:1px solid #E3E2DE;border-radius:14px;padding:34px;">
              <p style="margin:0 0 14px;font-family:'Courier New',Courier,monospace;font-size:11px;font-weight:700;letter-spacing:0.18em;text-transform:uppercase;color:#3F6212;mso-line-height-rule:exactly;line-height:16px;">{kicker_num} · {kicker_label}</p>
              <h1 style="margin:0 0 20px;font-family:Helvetica,Arial,sans-serif;font-size:27px;font-weight:700;letter-spacing:-0.02em;line-height:34px;mso-line-height-rule:exactly;color:#161614;">{headline}</h1>
              {body_html}
            </td>
          </tr>

{note_row}
          <!-- Footer -->
          <tr>
            <td align="center" style="padding:20px 0 32px;">
              <p style="margin:0;font-family:Helvetica,Arial,sans-serif;font-size:11px;line-height:18px;mso-line-height-rule:exactly;color:#9A9A94;text-align:center;">{addr}{unsub}</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>

</body>
</html>"""


# ---------------------------------------------------------------------------
# User-facing transactional emails
# ---------------------------------------------------------------------------

def send_verification_email(to_email: str, token: str, next_url: str | None = None) -> None:
    url = f"{BASE_URL}/verify?token={token}"
    # Thread a post-verification redirect through the email link so users who sign up from
    # a specific landing context (e.g. the demo CTA) land where they expect, not on /welcome.
    # Only allow relative paths to prevent open-redirect via a crafted registration.
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        url += "&next=" + urllib.parse.quote(next_url, safe="")
    logger.info("[email] verify link for %s: %s", to_email, url)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = (
        _p("Tap the button below to confirm your email and unlock your free 10-minute trial.")
        + _cta("Confirm my email", url)
        + _url_fallback(url)
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Confirm your email to start your free InterviewWise trial",
            "text": (
                "Welcome to InterviewWise!\n\n"
                "Confirm your email to unlock your free 10-minute trial:\n"
                f"{url}\n\n"
                "If you didn't sign up, you can safely ignore this email."
            ),
            "html": _email_html(
                preheader="Confirm your email to unlock your free 10-minute trial.",
                kicker_num="01",
                kicker_label="Get started",
                headline="Welcome to InterviewWise",
                body_html=body,
                note_line="If you didn&#8217;t sign up for InterviewWise, you can safely ignore this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send via Resend: %s", e)
        record_email_failure()


def send_password_reset_email(to_email: str, token: str) -> None:
    url = f"{BASE_URL}/reset-password?token={token}"
    logger.info("[email] password-reset link for %s: %s", to_email, url)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = (
        _p("Click below to set a new password. This link expires in 1 hour.")
        + _cta("Reset my password", url)
        + _url_fallback(url)
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Reset your InterviewWise password",
            "text": (
                "Reset your InterviewWise password\n\n"
                "Click the link below to set a new password. This link expires in 1 hour.\n"
                f"{url}\n\n"
                "If you didn't request a password reset, you can safely ignore this email."
            ),
            "html": _email_html(
                preheader="Reset your InterviewWise password — link expires in 1 hour.",
                kicker_num="02",
                kicker_label="Security",
                headline="Reset your password",
                body_html=body,
                note_line="If you didn&#8217;t request a password reset, you can safely ignore this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send reset email: %s", e)
        record_email_failure()


def send_install_link_email(to_email: str, token: str) -> None:
    url = f"{BASE_URL}/claim?token={token}"
    logger.info("[email] install link for %s: %s", to_email, url)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = (
        _p(
            "InterviewWise runs as a Chrome extension, so setup needs a laptop or desktop. "
            "Tap below &#8212; you&#8217;ll land already signed in, a few clicks from installing."
        )
        + _cta("Set up InterviewWise", url)
        + _url_fallback(url)
        + _p("This link works for 14 days. Don&#8217;t forward it &#8212; it signs you in.", small=True)
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewWise install link (open on your laptop)",
            "text": (
                "Open this on your laptop\n\n"
                "InterviewWise runs as a Chrome extension, so setup needs a laptop or desktop. "
                "Open this email there and use the link below — you'll land already signed in, "
                "one click from installing.\n"
                f"{url}\n\n"
                "This link works for 14 days. Don't forward it — it signs you in.\n\n"
                "If you didn't ask for an InterviewWise install link, you can safely ignore this email."
            ),
            "html": _email_html(
                preheader="Your InterviewWise install link — open this on a laptop or desktop.",
                kicker_num="03",
                kicker_label="Get started",
                headline="Open this on your laptop",
                body_html=body,
                note_line="If you didn&#8217;t ask for an InterviewWise install link, you can safely ignore this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send install link: %s", e)
        record_email_failure()


def send_desktop_login_email(to_email: str, token: str) -> None:
    url = f"{BASE_URL}/claim?token={token}"
    logger.info("[email] desktop sign-in link for %s: %s", to_email, url)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = (
        _p(
            "Open this email on the laptop or desktop you&#8217;ll interview from, "
            "then tap below &#8212; you&#8217;ll land signed in to your InterviewWise account."
        )
        + _cta("Sign in on this device", url)
        + _url_fallback(url)
        + _p(
            "This link expires in 15 minutes and can only be used once. "
            "Never forward it &#8212; it signs someone in to your account.",
            small=True,
        )
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewWise sign-in link (open on your laptop)",
            "text": (
                "Sign in on your laptop\n\n"
                "Open this email on the laptop or desktop you'll interview from, then use the "
                "link below — you'll land signed in to your InterviewWise account.\n"
                f"{url}\n\n"
                "This link expires in 15 minutes and can only be used once. "
                "Never forward it — it signs someone in to your account.\n\n"
                "If you didn't request this, you can safely ignore this email — your account is unchanged."
            ),
            "html": _email_html(
                preheader="Your one-time sign-in link for InterviewWise — expires in 15 minutes.",
                kicker_num="04",
                kicker_label="Sign in",
                headline="Pick up on your laptop",
                body_html=body,
                note_line="If you didn&#8217;t request this, your account is unchanged.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send desktop sign-in link: %s", e)
        record_email_failure()


def send_password_set_email(to_email: str) -> None:
    """Sent once when a /claim account gets a real password via /finish-signup.
    Not a token link — a plain security notice so the real owner can act even
    if this was triggered by someone who intercepted the claim link."""
    reset_url = f"{BASE_URL}/forgot-password"
    logger.info("[email] password-set notice for %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = (
        _p(
            f"Someone just finished setting up {to_email} with a password, "
            "so it can be signed into directly from now on."
        )
        + _p(
            "If this was you, there&#8217;s nothing else to do. If it wasn&#8217;t, "
            "reset it right away &#8212; you still control this inbox either way."
        )
        + _cta("Reset my password", reset_url)
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "A password was just set on your InterviewWise account",
            "text": (
                "Password set\n\n"
                f"Someone just finished setting up {to_email} with a password, "
                "so it can be signed into directly from now on.\n\n"
                "If this was you, there's nothing else to do. If it wasn't, reset it right "
                f"away — you still control this inbox either way.\n{reset_url}\n\n"
                "Questions? Just reply to this email."
            ),
            "html": _email_html(
                preheader=f"A password was just added to your InterviewWise account ({to_email}).",
                kicker_num="05",
                kicker_label="Security",
                headline="Password set",
                body_html=body,
                note_line="Questions? Just reply to this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send password-set notice: %s", e)
        record_email_failure()


# ---------------------------------------------------------------------------
# Account-status emails
# ---------------------------------------------------------------------------

def send_usage_warning_email(to_email: str) -> None:
    logger.info("[email] usage warning sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = (
        _p(
            "Your account has been sending far more requests than a typical interview "
            "session involves. This is a heads-up that we&#8217;ve flagged it for review."
        )
        + _p(
            "If this was you and there&#8217;s a good reason for it, no action is needed. "
            "If it continues, we may pause or restrict access to keep the service fair for everyone.",
            last=True,
        )
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Unusual activity on your InterviewWise account",
            "text": (
                "We've noticed unusual activity\n\n"
                "Your account has been sending far more requests than a typical interview session "
                "involves. This is a heads-up that we've flagged it for review.\n\n"
                "If this was you and there's a good reason for it, no action is needed. If it "
                "continues, we may pause or restrict access to keep the service fair for everyone.\n\n"
                "Questions? Just reply to this email."
            ),
            "html": _email_html(
                preheader="We've noticed unusual activity on your InterviewWise account.",
                kicker_num="06",
                kicker_label="Account",
                headline="Heads up on your account",
                body_html=body,
                note_line="Questions? Just reply to this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send usage warning: %s", e)
        record_email_failure()


def send_account_banned_email(to_email: str) -> None:
    logger.info("[email] ban notice sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = _p(
        "We&#8217;ve suspended access to your InterviewWise account. "
        "You won&#8217;t be able to log in or use the extension while it&#8217;s suspended.",
        last=True,
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewWise account has been suspended",
            "text": (
                "Your account has been suspended\n\n"
                "We've suspended access to your InterviewWise account. You won't be able to "
                "log in or use the extension while it's suspended.\n\n"
                "If you think this is a mistake, just reply to this email."
            ),
            "html": _email_html(
                preheader="Your InterviewWise account has been suspended.",
                kicker_num="07",
                kicker_label="Account",
                headline="Your account has been suspended",
                body_html=body,
                note_line="If you think this is a mistake, just reply to this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send ban notice: %s", e)
        record_email_failure()


def send_account_unbanned_email(to_email: str) -> None:
    logger.info("[email] unban notice sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = _p(
        "Your InterviewWise account is no longer suspended. "
        "You can log in and use the extension again as normal.",
        last=True,
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewWise account has been restored",
            "text": (
                "Your account has been restored\n\n"
                "Your InterviewWise account is no longer suspended. "
                "You can log in and use the extension again as normal.\n\n"
                "Questions? Just reply to this email."
            ),
            "html": _email_html(
                preheader="Your InterviewWise account is active again.",
                kicker_num="08",
                kicker_label="Account",
                headline="Your account has been restored",
                body_html=body,
                note_line="Questions? Just reply to this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send unban notice: %s", e)
        record_email_failure()


# ---------------------------------------------------------------------------
# Billing emails
# ---------------------------------------------------------------------------

def send_subscription_paused_email(to_email: str) -> None:
    logger.info("[email] subscription-paused notice sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = (
        _p("We&#8217;ve paused your InterviewWise subscription. Billing has stopped and your plan has been downgraded for now.")
        + _p("If you think this is a mistake, just reply to this email.", last=True)
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewWise subscription has been paused",
            "text": (
                "Your subscription has been paused\n\n"
                "We've paused your InterviewWise subscription. Billing has stopped and your "
                "plan has been downgraded for now.\n\n"
                "If you think this is a mistake, just reply to this email."
            ),
            "html": _email_html(
                preheader="Your InterviewWise subscription has been paused and billing stopped.",
                kicker_num="09",
                kicker_label="Billing",
                headline="Your subscription has been paused",
                body_html=body,
                note_line="If you think this is a mistake, just reply to this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send subscription-paused notice: %s", e)
        record_email_failure()


def send_subscription_resumed_email(to_email: str) -> None:
    logger.info("[email] subscription-resumed notice sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = _p(
        "Your InterviewWise subscription is active again and billing has resumed as normal.",
        last=True,
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewWise subscription has been resumed",
            "text": (
                "Your subscription has been resumed\n\n"
                "Your InterviewWise subscription is active again and billing has resumed as normal.\n\n"
                "Questions? Just reply to this email."
            ),
            "html": _email_html(
                preheader="Your InterviewWise subscription is active again — billing has resumed.",
                kicker_num="10",
                kicker_label="Billing",
                headline="Your subscription has been resumed",
                body_html=body,
                note_line="Questions? Just reply to this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send subscription-resumed notice: %s", e)
        record_email_failure()


def send_expiry_reminder_email(to_email: str, cancel_date: str) -> None:
    logger.info("[email] expiry reminder sent to %s (ends %s)", to_email, cancel_date)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    body = (
        _p(
            f"Your InterviewWise subscription is set to cancel on {cancel_date}. "
            "You&#8217;ll keep full access until then, and can undo this any time "
            "before that date from your account settings."
        )
        + _cta("Manage your subscription", f"{BASE_URL}/settings")
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your InterviewWise access ends soon",
            "text": (
                f"Your access ends on {cancel_date}\n\n"
                f"Your InterviewWise subscription is set to cancel on {cancel_date}. "
                "You'll keep full access until then, and can undo this any time before "
                f"that date from your account settings.\n{BASE_URL}/settings\n\n"
                "Questions? Just reply to this email."
            ),
            "html": _email_html(
                preheader=f"Your access ends on {cancel_date} — you can undo this any time before then.",
                kicker_num="11",
                kicker_label="Billing",
                headline=f"Your access ends on {cancel_date}",
                body_html=body,
                note_line="Questions? Just reply to this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send expiry reminder: %s", e)
        record_email_failure()


def send_low_sessions_email(to_email: str, sessions_remaining: int) -> None:
    logger.info("[email] low-sessions notice sent to %s (%d left)", to_email, sessions_remaining)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    plural = "session" if sessions_remaining == 1 else "sessions"
    body = (
        _p("Once they&#8217;re used up you&#8217;ll need to top up before starting another interview session.")
        + _cta("Top up sessions", f"{BASE_URL}/pricing")
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": f"{sessions_remaining} {plural} left on your InterviewWise account",
            "text": (
                f"You have {sessions_remaining} {plural} left\n\n"
                "Once they're used up you'll need to top up before starting another "
                f"interview session.\nTop up sessions: {BASE_URL}/pricing\n\n"
                "Questions? Just reply to this email."
            ),
            "html": _email_html(
                preheader=f"You have {sessions_remaining} {plural} left on your InterviewWise account.",
                kicker_num="12",
                kicker_label="Sessions",
                headline=f"You have {sessions_remaining} {plural} left",
                body_html=body,
                note_line="Questions? Just reply to this email.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send low-sessions notice: %s", e)
        record_email_failure()


# ---------------------------------------------------------------------------
# Lifecycle / engagement emails
# ---------------------------------------------------------------------------

def send_interview_reminder_email(to_email: str, full_name: str) -> None:
    logger.info("[email] interview reminder sent to %s", to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    first_name = (full_name or "").split(" ")[0] or "there"
    body = (
        _p(
            "Quick setup check before you go in: make sure the extension is installed, "
            "connected, and your phone or second device is signed in and propped up "
            "where you can glance at it."
        )
        + _cta("Check your setup", f"{BASE_URL}/settings")
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Your interview is tomorrow",
            "text": (
                f"Good luck tomorrow, {first_name}\n\n"
                "Quick setup check before you go in: make sure the extension is installed, "
                "connected, and your phone or second device is signed in and propped up "
                f"where you can glance at it.\nCheck your setup: {BASE_URL}/settings\n\n"
                "This is the only reminder you'll get from us about this interview. "
                "Questions? Just reply to this email."
            ),
            "html": _email_html(
                preheader=f"Quick setup check before your interview tomorrow, {first_name}.",
                kicker_num="13",
                kicker_label="Before you go in",
                headline=f"Good luck tomorrow, {first_name}",
                body_html=body,
                note_line=(
                    "This is the only reminder you&#8217;ll get from us about this interview. "
                    "Questions? Just reply to this email."
                ),
                show_unsubscribe=True,
                unsubscribe_label="Manage reminders",
                unsubscribe_url=f"{BASE_URL}/settings",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send interview reminder: %s", e)
        record_email_failure()


def send_announcement_email(to_email: str, subject: str, body: str) -> None:
    """Admin-authored announcement. Body is plain text; newlines become <br>."""
    logger.info("[email] announcement %r sent to %s", subject, to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    from html import escape
    body_html = _p(escape(body).replace("\n", "<br />"), last=True)

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "text": f"{body}\n\nQuestions? Just reply to this email.",
            "html": _email_html(
                preheader=(subject[:82] + "…") if len(subject) > 85 else subject,
                kicker_num="14",
                kicker_label="From InterviewWise",
                headline=subject,
                body_html=body_html,
                note_line="Questions? Just reply to this email.",
                show_unsubscribe=True,
                unsubscribe_label="Unsubscribe",
                unsubscribe_url=f"{BASE_URL}/settings",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send announcement to %s: %s", to_email, e)
        record_email_failure()


def send_lead_announcement_email(to_email: str, subject: str, body: str, token: str) -> None:
    """Admin-authored nudge to a captured-but-never-claimed lead.
    The token is freshly rotated per send — any prior link is already dead."""
    url = f"{BASE_URL}/claim?token={token}"
    logger.info("[email] lead announcement %r sent to %s", subject, to_email)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    from html import escape
    body_html = (
        _p(escape(body).replace("\n", "<br />"))
        + _cta("Set up InterviewWise", url)
        + _url_fallback(url)
        + _p(
            "InterviewWise runs as a Chrome extension &#8212; open this on a laptop or desktop. "
            "Don&#8217;t forward this link &#8212; it signs you in.",
            small=True,
        )
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": subject,
            "text": (
                f"{body}\n\n"
                f"Set up InterviewWise (open on a laptop or desktop):\n{url}\n\n"
                "Don't forward this link — it signs you in.\n\n"
                "You gave us this address on InterviewWise's site. If that wasn't you, "
                "ignore this email — no account has been created."
            ),
            "html": _email_html(
                preheader=(subject[:82] + "…") if len(subject) > 85 else subject,
                kicker_num="15",
                kicker_label="Get started",
                headline=subject,
                body_html=body_html,
                note_line=(
                    "You gave us this address on InterviewWise&#8217;s site. "
                    "If that wasn&#8217;t you, ignore this email &#8212; no account has been created."
                ),
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send lead announcement to %s: %s", to_email, e)
        record_email_failure()


# ---------------------------------------------------------------------------
# Internal / operator emails  (go to NOTIFY_EMAIL, not to users)
# ---------------------------------------------------------------------------

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
    outcome_label = "Kept subscription" if kept else "Cancelled"

    logger.info("[cancel-feedback] user=%s action=%s reason=%s", user_email, action, reason_label)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    from html import escape
    body = (
        _field("From", escape(user_email))
        + _field("Outcome", outcome_label)
        + _field("Reason", escape(reason_label))
        + (_block(escape(detail).replace("\n", "<br />")) if detail else "")
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": NOTIFY_EMAIL,
            "subject": f"[InterviewWise] Cancel feedback — {reason_label} ({action})",
            "text": f"Cancel page feedback\nFrom: {user_email}\nOutcome: {outcome_label}\nReason: {reason_label}\nDetail: {detail or 'No additional detail.'}",
            "html": _email_html(
                preheader=f"{outcome_label} · {reason_label} — from {user_email}",
                kicker_num="—",
                kicker_label="Cancel feedback",
                headline=reason_label,
                body_html=body,
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send cancel feedback: %s", e)
        record_email_failure()


def send_account_deletion_email(user_email: str, reason: str, detail: str) -> None:
    reason_label = _REASON_LABELS.get(reason, reason or "—")

    logger.info("[account-delete] user=%s reason=%s", user_email, reason_label)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    from html import escape
    body = (
        _field("From", escape(user_email))
        + _field("Reason", escape(reason_label))
        + (_block(escape(detail).replace("\n", "<br />")) if detail else "")
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": NOTIFY_EMAIL,
            "subject": f"[InterviewWise] Account deleted — {reason_label}",
            "text": f"Account deletion\nFrom: {user_email}\nReason: {reason_label}\nDetail: {detail or 'No additional detail.'}",
            "html": _email_html(
                preheader=f"Account deleted · {reason_label} — from {user_email}",
                kicker_num="—",
                kicker_label="Account deleted",
                headline=reason_label,
                body_html=body,
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send account deletion notice: %s", e)
        record_email_failure()


CONTACT_DEPT_LABELS = {
    "support":   "Support",
    "billing":   "Billing",
    "privacy":   "Privacy & Data",
    "legal":     "Legal",
    "partner":   "Partnerships",
    "marketing": "Marketing",
    "hello":     "General",
}

CONTACT_DEPT_ADDRESSES = {
    "support":   "support@interview-wise.com",
    "billing":   "billing@interview-wise.com",
    "privacy":   "privacy@interview-wise.com",
    "legal":     "legal@interview-wise.com",
    "partner":   "partner@interview-wise.com",
    "marketing": "marketing@interview-wise.com",
    "hello":     "hello@interview-wise.com",
}


def send_contact_email(dept: str, from_email: str, subject: str, message: str) -> None:
    """User-submitted contact form, routed to the right department inbox.
    reply_to is set to the user so a plain Reply goes back to them."""
    dept_label   = CONTACT_DEPT_LABELS.get(dept, "General")
    dept_address = CONTACT_DEPT_ADDRESSES.get(dept, "hello@interview-wise.com")

    logger.info("[contact] dept=%s from=%s subject=%r", dept, from_email, subject)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    from html import escape
    body = (
        _field("From", escape(from_email))
        + _field("Department", dept_label)
        + _block(escape(message).replace("\n", "<br />"))
    )
    short_subject = (subject[:57] + "…") if len(subject) > 60 else subject

    try:
        resend.Emails.send({
            "from":     FROM_EMAIL,
            "to":       dept_address,
            "reply_to": from_email,
            "subject":  f"[Contact: {dept_label}] {subject}",
            "text":     f"From: {from_email}\nDepartment: {dept_label}\nSubject: {subject}\n\n{message}",
            "html":     _email_html(
                preheader=f"{dept_label} · {from_email} — {subject}",
                kicker_num="—",
                kicker_label=f"Contact · {dept_label}",
                headline=short_subject,
                body_html=body,
                note_line="Hit reply to respond directly to this person.",
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send contact email: %s", e)
        record_email_failure()


def send_webstore_alert_email(detail: str, recovered: bool = False) -> None:
    """Operator alert for the Chrome Web Store listing going away or coming back.
    Edge-triggered — see _handle_webstore_transition in server.py."""
    logger.info("[webstore] alert email — recovered=%s detail=%s", recovered, detail)

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    headline = "Web Store listing is back" if recovered else "Web Store listing is down"
    description = (
        "The extension is published and installable again. No action needed."
        if recovered else
        "New users can&#8217;t install the extension. Check the Chrome Web Store developer "
        "dashboard for a policy notice, and consider setting "
        "<strong>SIDELOAD_ENABLED=1</strong> to serve the manual-install fallback page."
    )
    body = (
        _p(description)
        + _block(detail)
        + _cta("Open health dashboard", f"{BASE_URL}/admin/health")
    )

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": NOTIFY_EMAIL,
            "subject": f"[InterviewWise] {headline}",
            "text": f"{headline}\n\n{description}\n\nDetail: {detail}\n\nHealth: {BASE_URL}/admin/health",
            "html": _email_html(
                preheader=f"{'Recovered' if recovered else 'Action needed'} · Chrome Web Store · {detail[:60]}",
                kicker_num="—",
                kicker_label="System alert",
                headline=headline,
                body_html=body,
            ),
        })
    except Exception as e:
        logger.error("[email] failed to send webstore alert: %s", e)
        record_email_failure()
