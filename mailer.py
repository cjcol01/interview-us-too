import resend

from config import BASE_URL, FROM_EMAIL, RESEND_API_KEY

resend.api_key = RESEND_API_KEY

_PLACEHOLDER = "re_xxxxxxxxxxxx"


def send_verification_email(to_email: str, token: str) -> None:
    url = f"{BASE_URL}/verify?token={token}"
    print(f"[email] verify link for {to_email}: {url}")

    if not RESEND_API_KEY or RESEND_API_KEY == _PLACEHOLDER:
        return

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": to_email,
            "subject": "Verify your InterviewAce account",
            "html": f"""
            <div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#0d0d0d;color:#e0e0e0;">
              <h2 style="margin:0 0 16px;color:#fff;">Verify your email</h2>
              <p style="margin:0 0 24px;color:#aaa;line-height:1.6;">
                Click the button below to verify your email address and activate your account.
              </p>
              <a href="{url}" style="display:inline-block;background:#1e3a5f;color:#7eb8f7;
                 border-radius:8px;padding:12px 24px;text-decoration:none;font-weight:600;">
                Verify my email
              </a>
              <p style="margin:24px 0 0;color:#555;font-size:0.82rem;">
                Or copy this link: {url}
              </p>
            </div>
            """,
        })
    except Exception as e:
        print(f"[email] failed to send via Resend: {e}")
