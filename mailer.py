import resend

from config import BASE_URL, FROM_EMAIL, NOTIFY_EMAIL, RESEND_API_KEY

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


_REASON_LABELS = {
    "got_job":         "I got the job!",
    "too_expensive":   "Too expensive",
    "not_used_enough": "Didn't use it enough",
    "had_issues":      "It was buggy / I had issues",
    "missing_feature": "Missing a feature",
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

    print(f"[cancel-feedback] user={user_email} action={action} reason={reason_label} detail={detail!r}")

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
        print(f"[email] failed to send cancel feedback: {e}")
