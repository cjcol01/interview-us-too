from dotenv import load_dotenv
import os
import subprocess

load_dotenv()

# Bump these manually for major/minor releases; the patch number is the
# commit count, so it advances automatically on every push to main.
APP_VERSION_MAJOR = 0
APP_VERSION_MINOR = 3

def _commit_count() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "0"

APP_VERSION = f"{APP_VERSION_MAJOR}.{APP_VERSION_MINOR}.{_commit_count()}"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
RELOAD = os.getenv("RELOAD", "0") == "1"
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
if SECRET_KEY == "change-me-in-production":
    raise RuntimeError("SECRET_KEY env var is not set — add a secure random value to .env")

STRIPE_SECRET_KEY             = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET         = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID               = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_SESSIONS_PRICE_ID      = os.getenv("STRIPE_SESSIONS_INTRO_PRICE_ID", "")
STRIPE_SESSIONS_PACK_PRICE_ID = os.getenv("STRIPE_SESSIONS_PACK_PRICE_ID", "")
STRIPE_SUB_PRICE_ID           = os.getenv("STRIPE_SUB_PRICE_ID") or STRIPE_PRICE_ID
STRIPE_REFERRAL_COUPON_ID     = os.getenv("STRIPE_REFERRAL_COUPON_ID", "")
STRIPE_RETENTION_COUPON_ID   = os.getenv("STRIPE_RETENTION_COUPON_ID", "")
STRIPE_SUB_PRICE_PENCE        = int(os.getenv("STRIPE_SUB_PRICE_PENCE", "0"))

_missing = [
    name for name, val in [
        ("STRIPE_SECRET_KEY",             STRIPE_SECRET_KEY),
        ("STRIPE_SESSIONS_INTRO_PRICE_ID", STRIPE_SESSIONS_PRICE_ID),
        ("STRIPE_SESSIONS_PACK_PRICE_ID",  STRIPE_SESSIONS_PACK_PRICE_ID),
        ("STRIPE_SUB_PRICE_ID / STRIPE_PRICE_ID", STRIPE_SUB_PRICE_ID),
    ] if not val
]
if _missing:
    raise RuntimeError(f"Missing required env vars: {', '.join(_missing)}")
BASE_URL              = os.getenv("BASE_URL", "http://127.0.0.1:8000")

AI_PROMPT      = os.getenv("AI_PROMPT", "Describe what is happening on this screen. Be concise.")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
AUTHOR_PASSWORD = os.getenv("AUTHOR_PASSWORD", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL     = os.getenv("FROM_EMAIL", "onboarding@resend.dev")
NOTIFY_EMAIL   = os.getenv("NOTIFY_EMAIL", "cjcoleman267@gmail.com")
REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379/0")
POSTHOG_API_KEY  = os.getenv("POSTHOG_API_KEY", "")
LANDING_PROD     = os.getenv("LANDING_PROD", "1") == "1"
