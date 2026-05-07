from dotenv import load_dotenv
import os

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
if SECRET_KEY == "change-me-in-production":
    raise RuntimeError("SECRET_KEY env var is not set — add a secure random value to .env")

STRIPE_SECRET_KEY             = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET         = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID               = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_SESSIONS_PRICE_ID      = os.getenv("STRIPE_SESSIONS_INTRO_PRICE_ID", "")
STRIPE_SESSIONS_PACK_PRICE_ID = os.getenv("STRIPE_SESSIONS_PACK_PRICE_ID", "")
STRIPE_SUB_PRICE_ID           = os.getenv("STRIPE_SUB_PRICE_ID") or STRIPE_PRICE_ID

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
BASE_URL              = os.getenv("BASE_URL", "http://192.168.4.21:8000")

AI_PROMPT    = os.getenv("AI_PROMPT", "Describe what is happening on this screen. Be concise.")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL     = os.getenv("FROM_EMAIL", "onboarding@resend.dev")
NOTIFY_EMAIL   = os.getenv("NOTIFY_EMAIL", "cjcoleman267@gmail.com")
