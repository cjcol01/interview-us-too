from dotenv import load_dotenv
import os
import subprocess

load_dotenv()

# Bump these manually for major/minor releases; the patch number is the commit
# count less VERSION_PATCH_OFFSET, so it advances automatically on every push to main.
APP_VERSION_MAJOR = 0
APP_VERSION_MINOR = 4
VERSION_PATCH_OFFSET = 100

def _commit_count() -> int:
    try:
        return int(subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip())
    except Exception:
        return 0

APP_VERSION = f"{APP_VERSION_MAJOR}.{APP_VERSION_MINOR}.{max(_commit_count() - VERSION_PATCH_OFFSET, 0)}"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT") or os.getenv("PORT") or 8000)  # Railway injects PORT; local dev uses SERVER_PORT
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
STRIPE_REFERRAL_COUPON_ID     = os.getenv("STRIPE_REFERRAL_COUPON_ID", "")     # £5 off the referee's first paid plan
STRIPE_INTRO_FREE_COUPON_ID   = os.getenv("STRIPE_INTRO_FREE_COUPON_ID", "")   # 100%-off-once coupon: a referred user's free first session
STRIPE_RETENTION_COUPON_ID   = os.getenv("STRIPE_RETENTION_COUPON_ID", "")
STRIPE_SUB_PRICE_PENCE        = int(os.getenv("STRIPE_SUB_PRICE_PENCE", "0"))

# Sessions granted per one-time purchase. Amounts (the £2 / £10 charged) live in Stripe;
# only how many sessions each grants lives here.
INTRO_SESSIONS = int(os.getenv("INTRO_SESSIONS", "1"))   # £2 intro → 1 session
PACK_SESSIONS  = int(os.getenv("PACK_SESSIONS",  "3"))   # £10 pack → 3 sessions

# Partner (affiliate) programme — a three-tier ladder:
#   Tier 1 (implicit — every user): a flat one-off cash reward (PARTNER_TIER1_FLAT_PENCE) per
#           referee who converts to a real paid plan (£10 pack or £15 sub). Never on the £2 intro.
#   Tier 2 (auto at PARTNER_TIER2_MIN_PAID paid referrals, or granted manually): recurring %.
#   Tier 3 (manual only — e.g. granted during outreach): higher recurring %.
# Recurring rates are in basis points (1500 = 15%). partner_tier 2 → Tier 2, 3 → Tier 3;
# anything below (0/1) is the implicit flat Tier 1.
PARTNER_TIER1_FLAT_PENCE = int(os.getenv("PARTNER_TIER1_FLAT_PENCE", "500"))   # £5 flat
PARTNER_TIER2_BPS        = int(os.getenv("PARTNER_TIER2_BPS", "1500"))         # 15%
PARTNER_TIER3_BPS        = int(os.getenv("PARTNER_TIER3_BPS", "2500"))         # 25%
PARTNER_TIER2_MIN_PAID   = int(os.getenv("PARTNER_TIER2_MIN_PAID", "3"))
PARTNER_HOLD_DAYS        = int(os.getenv("PARTNER_HOLD_DAYS", "60"))
PARTNER_WITHDRAWAL_THRESHOLD_PENCE = int(os.getenv("PARTNER_WITHDRAWAL_THRESHOLD_PENCE", "2000"))  # £20 min payout

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

# Google OAuth ("Continue with Google") — optional. Unset, the login page just hides the
# button and the /auth/google* routes 404, so the server starts fine without it.
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_OAUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

# GitHub OAuth ("Continue with GitHub") — optional, same pattern as Google above. Unset, the
# login page hides the button and the /auth/github* routes 404.
GITHUB_CLIENT_ID     = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_OAUTH_ENABLED = bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)

# Shared base prompt, prepended to every capture regardless of how the input arrived. The
# part that differs per input method (screenshot / typed / mic / replay) is NOT here — it
# lives in server.py's INPUT_MODE_PROMPT, because those deltas describe the shape of the
# input rather than anything an operator would want to reconfigure. Override this to change
# the assistant's voice and standing rules; the per-method wording stays put.
AI_PROMPT      = os.getenv("AI_PROMPT", "You're an AI assistant built into an interview preparation tool, helping a candidate work through interview questions. Reply as helpfully and concisely as possible — no greetings, no preamble, no restating the question back. You may be given background context about the candidate or interview (company, role, CV notes) appended after these instructions; treat it as passive reference material only, and factor it in only if directly relevant to the specific question asked — otherwise ignore it completely. Detect the programming language in use; fall back to Python 3 if you can't tell. If the input is incomplete, fragmented or unclear, do the best you can to work out what the question was and what the most helpful answer would be, rather than stalling to ask for a clearer one. For behavioural questions, answer in STAR format with S- / T- / A- / R- on separate lines.")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
# Optional failover providers — capture/transcription still work without them, just without
# the extra resilience if the primary provider (Claude / Whisper) is down. See server.py's
# _stream_ai_response and the audio-capture route.
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
AUTHOR_PASSWORD = os.getenv("AUTHOR_PASSWORD", "")
# Username whose session cookie is trusted as the admin account by _require_author, and the
# Basic-auth username the same check accepts alongside AUTHOR_PASSWORD. Kept in env rather
# than hardcoded in server.py because this repo is public (see the jsDelivr URL below) — a
# literal here names the one account worth attacking. Unset, there is no cookie-based admin
# and no Basic-auth match either, so /admin and friends are simply unreachable (fail closed).
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
RESEND_API_KEY   = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL       = os.getenv("FROM_EMAIL", "onboarding@resend.dev")
NOTIFY_EMAIL     = os.getenv("NOTIFY_EMAIL", "cjcoleman267@gmail.com")
# Physical address shown in email footers — required by CAN-SPAM / PECR.
# Set this to your registered business address before going live.
COMPANY_ADDRESS  = os.getenv("COMPANY_ADDRESS", "20 Wenlock Road, London, England, N1 7GU")
REDIS_URL        = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Postgres connection URLs. Railway injects DATABASE_URL automatically when a Postgres service
# is attached. Normalise "postgres://" → "postgresql://" because SQLAlchemy 2.x rejects the
# bare form. database.py raises with a helpful message if the relevant URL is unset at boot.
DATABASE_URL      = os.getenv("DATABASE_URL",      "").replace("postgres://", "postgresql://", 1)
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "").replace("postgres://", "postgresql://", 1)

# Directory for non-DB persistent files: app.log (analytics.py), disk health checks
# (server.py). Defaults outside the repo so a WSL2 dev machine (9p-mounted repo) can still
# write logs reliably. On Railway/VPS, point this at a mounted volume so logs survive redeploys.
DB_DATA_DIR      = os.getenv("DB_DATA_DIR", "~/.interview-us-too")
POSTHOG_API_KEY  = os.getenv("POSTHOG_API_KEY", "")
LANDING_PROD     = os.getenv("LANDING_PROD", "1") == "1"

# Manual-install fallback page (/install-manual), for if the Chrome Web Store listing is
# ever taken down or delisted. Off by default — the route 404s until this is flipped on,
# so the page doesn't sit around half-finished or confuse users during normal operation.
# The zip is committed to the repo at static/extension/ (see scripts/build_extension_zip.py)
# and served two ways: same-origin (SIDELOAD_ZIP_URL default) and via jsDelivr's CDN fronting
# the public GitHub repo, which stays reachable even if our own server is what's struggling.
# jsDelivr caches @main aggressively — after updating the zip, purge with a GET to
# https://purge.jsdelivr.net/gh/cjcol01/interview-us-too@main/static/extension/interview-wise-extension.zip
SIDELOAD_ENABLED = os.getenv("SIDELOAD_ENABLED", "0") == "1"
SIDELOAD_ZIP_URL = os.getenv(
    "SIDELOAD_ZIP_URL",
    "https://cdn.jsdelivr.net/gh/cjcol01/interview-us-too@main/static/extension/interview-wise-extension.zip",
)

# 32-char Chrome Web Store item ID of the published extension (the last path segment of its
# listing URL). Set this once the extension is live and /admin/health will watch the listing
# and flag a takedown/unpublish — see _check_webstore in server.py. Left unset, that check
# reports "not configured" instead of guessing at an ID.
WEBSTORE_EXTENSION_ID = os.getenv("WEBSTORE_EXTENSION_ID", "")

# --- Dev-only settings: review/change before deploying to production -------
# SKIP_EMAIL_VERIFICATION: when "1", new accounts are marked verified on signup
# and no verification email is sent. Convenient for local dev; must be unset
# (or "0") in production or every signup skips email verification.
SKIP_EMAIL_VERIFICATION = os.getenv("SKIP_EMAIL_VERIFICATION", "0") == "1"

# DEV_BUILD: master switch for dev-only conveniences gated behind it elsewhere
# in the codebase. Must be unset (or "0") in production.
DEV_BUILD = os.getenv("DEV_BUILD", "0") == "1"
