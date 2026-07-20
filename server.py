import asyncio
import base64
import json
import os
import re
import secrets
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from urllib.parse import urlencode

import anthropic
import redis.asyncio as aioredis
import redis.exceptions as redis_exceptions
import stripe
import uvicorn
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, aliased
from starlette.exceptions import HTTPException as StarletteHTTPException

from analytics import identify, logger, track
from auth import create_token, decode_user_id, generate_unique_referral_code, get_current_user, get_optional_user, get_user_by_token, hash_password, verify_password
from billing import apply_retention_coupon, cancel_subscription, cancel_subscription_immediately, create_checkout_session, create_portal_session, handle_webhook_event, pause_subscription, resume_subscription
from config import AI_PROMPT, ANTHROPIC_API_KEY, APP_VERSION, AUTHOR_PASSWORD, BASE_URL, LANDING_PROD, OPENAI_API_KEY, PARTNER_HOLD_DAYS, PARTNER_JOIN_MIN_SIGNUPS, PARTNER_TIER1_BPS, PARTNER_TIER2_BPS, PARTNER_TIER2_MIN_PAID, POSTHOG_API_KEY, RELOAD, REDIS_URL, SERVER_HOST, SERVER_PORT, SKIP_EMAIL_VERIFICATION, STRIPE_REFERRAL_COUPON_ID, STRIPE_SUB_PRICE_PENCE
from mailer import send_account_banned_email, send_account_deletion_email, send_account_unbanned_email, send_cancel_feedback_email, send_password_reset_email, send_subscription_paused_email, send_subscription_resumed_email, send_usage_warning_email, send_verification_email
from database import SessionLocal, get_db, init_db
from models import AccountLevel, CommissionStatus, InterviewContext, InterviewSession, PartnerCommission, Referral, ReferralStatus, ResponseStyle, UsageDaily, User

# test comment for cicd
def _optional_user_from_request(request: Request) -> Optional[User]:
    # Reuse the user cached by get_optional_user() when it already ran as a route dependency.
    if hasattr(request.state, "user"):
        return request.state.user
    token = request.cookies.get("session")
    user_id = decode_user_id(token) if token else None
    user = None
    if user_id:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id, User.is_active == True).first()  # noqa: E712
        finally:
            db.close()
    request.state.user = user
    return user


def _template_globals(request: Request) -> dict:
    """Jinja2 context processor: makes `user`/`account_level`/`sessions_remaining`
    available on every template render so routes can't forget the navbar's auth
    state (this previously drifted out of sync on several pages)."""
    user = _optional_user_from_request(request)
    return {
        "user": user,
        "account_level": user.account_level.value if user else "free",
        "sessions_remaining": user.sessions_remaining if user else 0,
        "unseen_account_flag": bool(user and user.account_flag and not user.account_flag_seen),
    }


templates = Jinja2Templates(directory="templates", context_processors=[_template_globals])
templates.env.globals["POSTHOG_KEY"] = POSTHOG_API_KEY
templates.env.globals["POSTHOG_HOST"] = os.getenv("POSTHOG_HOST", "https://eu.i.posthog.com")
templates.env.globals["APP_VERSION"] = APP_VERSION
SCREENSHOTS_DIR = Path("screenshots")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    if os.getenv("TESTING") == "1":
        import fakeredis.aioredis
        app.state.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    else:
        app.state.redis = aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
            socket_keepalive=True,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        for attempt in range(5):
            try:
                await app.state.redis.ping()
                break
            except (redis_exceptions.TimeoutError, redis_exceptions.ConnectionError):
                if attempt == 4:
                    raise
                logger.warning("Redis not reachable yet (attempt %d/5) — retrying in 2s", attempt + 1)
                await asyncio.sleep(2)
    logger.info("[ready] http://localhost:%d", SERVER_PORT)
    try:
        yield
    finally:
        await app.state.redis.aclose()


app = FastAPI(lifespan=lifespan)
app.mount("/css", StaticFiles(directory="css"), name="css")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

_SKIP_LOG_PREFIXES = ("/css/", "/favicon")

@app.middleware("http")
async def _request_logger(request: Request, call_next):
    if any(request.url.path.startswith(p) for p in _SKIP_LOG_PREFIXES):
        return await call_next(request)
    start = time.time()
    user_id = None
    token = request.cookies.get("session")
    if token:
        user_id = decode_user_id(token)
    response = await call_next(request)
    ms = int((time.time() - start) * 1000)
    logger.info("%s %s → %d (%dms) user=%s", request.method, request.url.path, response.status_code, ms, user_id)
    return response


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _build_404_ref(path: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-").upper()
    return f"REQ-00404-{slug}" if slug else "REQ-00404-NF"


@app.exception_handler(StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and "text/html" in request.headers.get("accept", ""):
        ctx = {"ref_code": _build_404_ref(request.url.path), "show_navbar": True}
        return templates.TemplateResponse(request=request, name="404.html", context=ctx, status_code=404)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


async_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

SESSION_DURATION = timedelta(hours=2, minutes=30)
TRIAL_DURATION   = timedelta(minutes=10)

COMPLEXITY_MIN = 1
COMPLEXITY_MAX = 3
COMPLEXITY_SUFFIX = {
    1: "\n\nComplexity level: 1/3 — give the naive approach. Simple, readable code that works but is not optimised. Brief explanation.",
    2: "\n\nComplexity level: 2/3 — give the approach a skilled but junior developer would write. Reasonably efficient, clean code with a short explanation of the reasoning.",
    3: "\n\nComplexity level: 3/3 — give the optimal approach. Best time/space complexity, clean production-quality code, with a thorough explanation including trade-offs and edge cases.",
}


class HotkeySettings(BaseModel):
    capture: str
    audio:   str
    toggle:  str
    replay:  str
    typing:  str


HOTKEY_DEFAULTS = {"capture": "Ctrl+Shift+7", "audio": "Ctrl+Shift+8", "toggle": "Ctrl+Shift+9", "replay": "Ctrl+Shift+6", "typing": "Ctrl+Shift+5"}

REPLAY_SECONDS_MIN = 1
REPLAY_SECONDS_MAX = 30


class ReplaySettings(BaseModel):
    enabled: bool
    seconds: int = Field(ge=REPLAY_SECONDS_MIN, le=REPLAY_SECONDS_MAX)

RESPONSE_STYLE_DEFAULT = ResponseStyle.conversational
RESPONSE_STYLE_SUFFIX = {
    ResponseStyle.conversational: "",
    ResponseStyle.bullets:        "\n\nFormat your entire response as concise bullet points.",
    ResponseStyle.summary:        "\n\nKeep your response to a brief 2-3 sentence summary only.",
    ResponseStyle.one_liner:      "\n\nRespond in a single sentence only.",
}


class ResponseStyleRequest(BaseModel):
    style: ResponseStyle


MAX_CONTEXTS_PER_USER   = 5
CONTEXT_NAME_MAX_LENGTH = 60
CONTEXT_TEXT_MAX_LENGTH = 2000


class ContextSaveRequest(BaseModel):
    slot: int = Field(ge=1, le=MAX_CONTEXTS_PER_USER)
    name: str = Field(default="", max_length=CONTEXT_NAME_MAX_LENGTH)
    text: str = Field(default="", max_length=CONTEXT_TEXT_MAX_LENGTH)


class ContextActivateRequest(BaseModel):
    slot: Optional[int] = Field(default=None, ge=1, le=MAX_CONTEXTS_PER_USER)


def _context_suffix(user, db: Session) -> str:
    if not user.active_context_slot:
        return ""
    ctx = db.query(InterviewContext).filter(
        InterviewContext.user_id == user.id,
        InterviewContext.slot == user.active_context_slot,
    ).first()
    if not ctx or not ctx.text:
        return ""
    return f"\n\nAdditional context provided by the candidate about this interview:\n{ctx.text}"


def _user_hotkeys(user) -> dict:
    return {
        "capture": user.hotkey_capture or HOTKEY_DEFAULTS["capture"],
        "audio":   user.hotkey_audio   or HOTKEY_DEFAULTS["audio"],
        "toggle":  user.hotkey_toggle  or HOTKEY_DEFAULTS["toggle"],
        "replay":  user.hotkey_replay  or HOTKEY_DEFAULTS["replay"],
        "typing":  user.hotkey_typing  or HOTKEY_DEFAULTS["typing"],
    }


def _user_response_style(user) -> ResponseStyle:
    return user.response_style or RESPONSE_STYLE_DEFAULT


_CAPTURE_DEFAULTS = {"analysis": "", "timestamp": "", "capture_id": "0", "monitor": ""}

def _capture_key(uid: int) -> str:    return f"user:{uid}:capture"
def _complexity_key(uid: int) -> str: return f"user:{uid}:complexity"
def _events_channel(uid: int) -> str: return f"user:{uid}:events"


async def get_capture_state(r, user_id: int) -> dict:
    data = await r.hgetall(_capture_key(user_id))
    merged = {**_CAPTURE_DEFAULTS, **data}
    merged["capture_id"] = int(merged["capture_id"])
    return merged


async def get_complexity(r, user_id: int) -> int:
    val = await r.get(_complexity_key(user_id))
    return int(val) if val is not None else 2


def _get_or_create_session(db: Session, user_id: int, duration: timedelta = SESSION_DURATION) -> InterviewSession:
    now = datetime.utcnow()
    session = db.query(InterviewSession).filter(
        InterviewSession.user_id == user_id,
        InterviewSession.expires_at > now,
        InterviewSession.ended_at == None,  # noqa: E711
    ).first()
    if not session:
        session = InterviewSession(
            user_id=user_id,
            started_at=now,
            expires_at=now + duration,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def require_subscription(user: User = Depends(get_current_user)) -> User:
    if user.account_level == AccountLevel.free:
        raise HTTPException(status_code=403, detail="Subscription required")
    return user


async def _rate_limit(r, user_id: int, endpoint: str, cooldown: int, limit: int,
                      cooldown_msg: str = "Too fast — wait a moment before trying again",
                      limit_msg: str = "Rate limit exceeded — try again in a minute",
                      window_limit: int = None, window_seconds: int = 300,
                      window_msg: str = "Rate limit exceeded — try again in a few minutes"):
    last_key  = f"rl:{user_id}:{endpoint}:last"
    count_key = f"rl:{user_id}:{endpoint}:count"
    window_key = f"rl:{user_id}:{endpoint}:window_count"
    last = await r.get(last_key)
    if last and (time.time() - float(last)) < cooldown:
        await broadcast(r, user_id, "rate_limited", {"message": cooldown_msg})
        raise HTTPException(status_code=429, detail=cooldown_msg)
    count = await r.incr(count_key)
    if count == 1:
        await r.expire(count_key, 60)
    if count > limit:
        await broadcast(r, user_id, "rate_limited", {"message": limit_msg})
        raise HTTPException(status_code=429, detail=limit_msg)
    if window_limit is not None:
        window_count = await r.incr(window_key)
        if window_count == 1:
            await r.expire(window_key, window_seconds)
        if window_count > window_limit:
            await broadcast(r, user_id, "rate_limited", {"message": window_msg})
            raise HTTPException(status_code=429, detail=window_msg)
    await r.set(last_key, time.time(), ex=cooldown + 5)


def _record_usage(db: Session, user_id: int, kind: str):
    """Persistent per-user, per-UTC-day counter for the admin usage page — separate from
    the short-lived Redis rate-limit keys, which expire after minutes."""
    today = datetime.utcnow().date()
    row = db.query(UsageDaily).filter(UsageDaily.user_id == user_id, UsageDaily.date == today).first()
    if not row:
        row = UsageDaily(user_id=user_id, date=today, capture_count=0, audio_count=0)
        db.add(row)
    if kind == "capture":
        row.capture_count += 1
    else:
        row.audio_count += 1
    db.commit()


async def broadcast(r, user_id: int, event_type: str, data: dict):
    payload = json.dumps({"type": event_type, **data})
    await r.publish(_events_channel(user_id), payload)


# Raises a redirect to /login — use as a dependency on page routes that require auth.
class _Unauthenticated(Exception):
    pass

@app.exception_handler(_Unauthenticated)
async def _unauthenticated_handler(request: Request, exc: _Unauthenticated):
    return RedirectResponse("/login", status_code=302)

def require_user(user: Optional[User] = Depends(get_optional_user)) -> User:
    if not user:
        raise _Unauthenticated()
    return user


async def _gate_basic_access(r, user: User, db: Session):
    """Raise 403 if free or trial-expired. Shared by capture + audio endpoints."""
    if user.account_level == AccountLevel.free:
        raise HTTPException(status_code=403, detail="Subscription required")
    if user.account_level == AccountLevel.trial:
        now = datetime.utcnow()
        active = db.query(InterviewSession).filter(
            InterviewSession.user_id == user.id,
            InterviewSession.expires_at > now,
            InterviewSession.ended_at == None,  # noqa: E711
        ).first()
        if not active:
            user.account_level = AccountLevel.free
            db.commit()
            track(user.id, "trial_expired")
            await broadcast(r, user.id, "trial_expired", {})
            raise HTTPException(status_code=403, detail="trial_expired")


def _ensure_api_token(user: User, db: Session):
    if not user.api_token:
        user.api_token = secrets.token_urlsafe(32)
        db.commit()


_REFERRAL_ERROR_MESSAGES = {
    "invalid_code":       "That code doesn't look right — double-check and try again.",
    "already_referred":   "You've already applied a referral code.",
    "self_referral":      "You can't use your own referral code.",
    "reciprocal_referral": "That person already used your referral code — you can't refer each other.",
    "already_paid":       "Referral codes can only be applied before your first payment.",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    full_name: str
    username: str
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class CaptureRequest(BaseModel):
    image: str        # base64 PNG, optionally prefixed with "data:image/png;base64,"
    complexity: int = Field(default=2, ge=1, le=3)
    monitor: str = "browser"


class TextCaptureRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    monitor: str = "browser"


# ---------------------------------------------------------------------------
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


@app.get("/502", include_in_schema=False)
async def preview_502():
    # Dev-only preview of the static page the reverse proxy serves when the app
    # itself is down (see static/502.html) — served at 200 here since the app
    # answering at all means there's no real gateway error to report.
    return FileResponse("static/502.html", media_type="text/html")


# Auth routes
# ---------------------------------------------------------------------------

@app.get("/login")
async def login_page(request: Request, user: Optional[User] = Depends(get_optional_user), next: Optional[str] = None):
    if user:
        return RedirectResponse(next or "/app")
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.post("/auth/login")
async def auth_login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account has been suspended. Contact support if you think this is a mistake.")

    user.last_login = datetime.utcnow()
    db.commit()
    track(user.id, "login")

    token = create_token(user.id)
    response = JSONResponse({"status": "ok", "username": user.username})
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return response


@app.post("/auth/register")
async def auth_register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
    ref: Optional[str] = Cookie(default=None),
):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=400, detail="Username already taken.")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="Email already registered.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    user = User(
        username=body.username,
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
        account_level=AccountLevel.trial,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    user.referral_code = generate_unique_referral_code(db)

    if ref:
        referrer = db.query(User).filter(User.referral_code == ref).first()
        if referrer and referrer.id != user.id:
            user.referred_by_id = referrer.id
            db.add(Referral(referrer_id=referrer.id, referee_id=user.id))

    if SKIP_EMAIL_VERIFICATION:
        user.email_verified = True
    else:
        verify_token = secrets.token_urlsafe(32)
        user.verify_token = verify_token
        db.commit()
        send_verification_email(user.email, verify_token)
    db.commit()
    identify(user.id, user.email, user.full_name, user.account_level.value)
    track(user.id, "signup", referred=bool(ref))

    token = create_token(user.id)
    response = JSONResponse({"status": "ok", "username": user.username})
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    response.delete_cookie("ref")
    return response


@app.post("/auth/resend-verification")
async def resend_verification(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.email_verified:
        raise HTTPException(status_code=400, detail="Email already verified.")
    user.verify_token = secrets.token_urlsafe(32)
    db.commit()
    send_verification_email(user.email, user.verify_token)
    return {"status": "ok"}


@app.get("/verify")
async def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.verify_token == token).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link.")
    user.email_verified = True
    user.verify_token = None
    db.commit()
    track(user.id, "email_verified", account_level=user.account_level.value)
    if user.account_level == AccountLevel.trial:
        return RedirectResponse("/onboarding")
    return RedirectResponse("/app")


@app.get("/forgot-password")
async def forgot_password_page(request: Request, user: Optional[User] = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/app")
    return templates.TemplateResponse(request=request, name="forgot_password.html", context={})


@app.post("/auth/forgot-password")
async def auth_forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email, User.is_active == True).first()
    if user:
        user.reset_token = secrets.token_urlsafe(32)
        user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
        db.commit()
        send_password_reset_email(user.email, user.reset_token)
    # Always return ok — never reveal whether the email is registered
    return {"status": "ok"}


@app.get("/reset-password")
async def reset_password_page(request: Request, token: str = "", db: Session = Depends(get_db)):
    # Pre-validate so we can show a useful error on stale/bad links
    user = db.query(User).filter(User.reset_token == token).first() if token else None
    invalid = not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow()
    return templates.TemplateResponse(
        request=request,
        name="reset_password.html",
        context={"token": token, "invalid": invalid},
    )


@app.post("/auth/reset-password")
async def auth_reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == body.token).first()
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    user.password_hash = hash_password(body.new_password)
    user.reset_token = None
    user.reset_token_expiry = None
    db.commit()
    track(user.id, "password_reset")
    return {"status": "ok"}


@app.post("/auth/logout")
@app.get("/auth/logout")
async def auth_logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response


# ---------------------------------------------------------------------------
# App routes
# ---------------------------------------------------------------------------

@app.get("/")
async def landing(request: Request, user: Optional[User] = Depends(get_optional_user)):
    template = "landing.html" if LANDING_PROD else "landing_prep.html"
    ctx = {"show_navbar": True, "show_landing_links": True}
    return templates.TemplateResponse(request=request, name=template, context=ctx)


@app.get("/app")
async def index(request: Request, user: User = Depends(require_user)):
    if not user.email_verified:
        return RedirectResponse("/verify-pending")
    if user.account_level == AccountLevel.free:
        return RedirectResponse("/pricing")
    if user.account_level == AccountLevel.trial and not user.setup_complete:
        return RedirectResponse("/onboarding")
    return templates.TemplateResponse(request=request, name="index.html", context={
        **_user_hotkeys(user),
        "show_navbar": True,
    })


@app.get("/onboarding")
async def onboarding_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not user.email_verified:
        return RedirectResponse("/verify-pending")
    if user.account_level != AccountLevel.trial:
        return RedirectResponse("/app")
    _ensure_api_token(user, db)
    track(user.id, "onboarding_viewed")
    hk = _user_hotkeys(user)
    return templates.TemplateResponse(request=request, name="onboarding.html", context={
        "api_token": user.api_token,
        "base_url": BASE_URL,
        "hotkey_capture": hk["capture"],
        "hotkey_audio":   hk["audio"],
        "hotkey_toggle":  hk["toggle"],
        "hotkey_replay":  hk["replay"],
        "hotkey_typing":  hk["typing"],
    })


@app.get("/verify-pending")
async def verify_pending(request: Request, user: User = Depends(require_user)):
    if user.email_verified:
        return RedirectResponse("/app")
    return templates.TemplateResponse(request=request, name="verify_pending.html", context={
        "email": user.email,
    })


@app.get("/trial-end")
async def trial_end(request: Request, user: User = Depends(require_user)):
    hk = _user_hotkeys(user)
    return templates.TemplateResponse(request=request, name="trial_end.html", context={
        "hotkey_capture": hk["capture"],
        "hotkey_audio":   hk["audio"],
        "hotkey_toggle":  hk["toggle"],
        "hotkey_replay":  hk["replay"],
    })


@app.get("/pricing")
async def pricing_page(request: Request, user: Optional[User] = Depends(get_optional_user)):
    if user and user.account_level == AccountLevel.unlimited:
        return RedirectResponse("/settings", status_code=302)
    if user:
        track(user.id, "pricing_viewed", account_level=user.account_level.value)
    return templates.TemplateResponse(request=request, name="pricing.html", context={
        "logged_in": user is not None,
        "intro_redeemed": user.intro_redeemed if user else False,
        "is_referred": user.referred_by_id is not None if user else False,
        "referral_discount_active": bool(STRIPE_REFERRAL_COUPON_ID),
        "referral_credit_pence": user.referral_credit_pence if user else 0,
        "sub_price_pence": STRIPE_SUB_PRICE_PENCE,
        "show_navbar": True,
    })


_basic = HTTPBasic(auto_error=False)
_ADMIN_USERNAME = "cjcol01"

def _require_author(
    user: Optional[User] = Depends(get_optional_user),
    credentials: Optional[HTTPBasicCredentials] = Depends(_basic),
):
    if user and user.username == _ADMIN_USERNAME:
        return
    if (
        credentials
        and AUTHOR_PASSWORD
        and secrets.compare_digest(credentials.username.encode(), _ADMIN_USERNAME.encode())
        and secrets.compare_digest(credentials.password.encode(), AUTHOR_PASSWORD.encode())
    ):
        return
    raise HTTPException(status_code=401, headers={"WWW-Authenticate": 'Basic realm="author"'})

@app.get("/verify-author")
async def author_page(request: Request, _: None = Depends(_require_author)):
    return templates.TemplateResponse(request=request, name="author.html", context={"show_navbar": True})


@app.get("/r/{code}")
async def referral_redirect(
    code: str,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if user:
        return RedirectResponse("/app")
    referrer = db.query(User).filter(User.referral_code == code).first()
    response = RedirectResponse("/login", status_code=302)
    if referrer:
        response.set_cookie("ref", code, max_age=30 * 24 * 60 * 60, httponly=True, samesite="lax")
    return response


@app.get("/referral")
async def referral_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    ref_success: Optional[str] = None,
    ref_error: Optional[str] = None,
):
    if not user.referral_code:
        user.referral_code = generate_unique_referral_code(db)
        db.commit()
    referral_rows = (
        db.query(Referral, User)
        .join(User, User.id == Referral.referee_id)
        .filter(Referral.referrer_id == user.id)
        .order_by(Referral.created_at.desc())
        .all()
    )
    referrals = []
    for ref_row, referee_user in referral_rows:
        referrals.append({
            "referee_name": referee_user.username,
            "joined_date": f"{ref_row.created_at.day} {ref_row.created_at.strftime('%b %Y')}",
            "status": ref_row.status.value,
            "referee_level": referee_user.account_level.value,
        })
    return templates.TemplateResponse(request=request, name="referral.html", context={
        "referral_code": user.referral_code,
        "referrals": referrals,
        "referral_credit_pence": user.referral_credit_pence,
        "is_referred": user.referred_by_id is not None,
        "referral_discount_active": bool(STRIPE_REFERRAL_COUPON_ID),
        "ref_success": ref_success == "1",
        "error_msg": _REFERRAL_ERROR_MESSAGES.get(ref_error),
        "show_navbar": True,
    })


def _parse_referral_code(raw: str) -> str:
    """Accept a bare code or a full /r/<code> URL — return just the code."""
    raw = raw.strip()
    if "/r/" in raw:
        return raw.split("/r/")[-1].strip("/").strip()
    return raw


@app.post("/referral/apply")
async def apply_referral_code(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    code: str = Form(...),
    source: str = Form(default="referral"),
):
    def redirect(param: str, value: str):
        base = "/settings" if source == "settings" else "/referral"
        return RedirectResponse(f"{base}?{param}={value}", status_code=303)

    if user.referred_by_id or db.query(Referral).filter(Referral.referee_id == user.id).first():
        return redirect("ref_error", "already_referred")
    if user.intro_redeemed or user.sub_invoice_paid or user.account_level in (AccountLevel.paid, AccountLevel.unlimited):
        return redirect("ref_error", "already_paid")
    referrer = db.query(User).filter(User.referral_code == _parse_referral_code(code)).first()
    if not referrer:
        return redirect("ref_error", "invalid_code")
    if referrer.id == user.id:
        return redirect("ref_error", "self_referral")
    if db.query(Referral).filter(Referral.referrer_id == user.id, Referral.referee_id == referrer.id).first():
        return redirect("ref_error", "reciprocal_referral")
    user.referred_by_id = referrer.id
    db.add(Referral(referrer_id=referrer.id, referee_id=user.id))
    db.commit()
    track(user.id, "referral_applied")
    return redirect("ref_success", "1")


def _partner_counts(user: User, db: Session) -> tuple[int, int]:
    """(total referral signups, fully-paying referees) for a given referrer."""
    signup_count = db.query(Referral).filter(Referral.referrer_id == user.id).count()
    paid_count = db.query(Referral).filter(
        Referral.referrer_id == user.id,
        Referral.status == ReferralStatus.subscribed,
    ).count()
    return signup_count, paid_count


@app.get("/partner")
async def partner_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    joined: str = Query(default=""),
):
    signup_count, paid_count = _partner_counts(user, db)
    return templates.TemplateResponse(request=request, name="partner.html", context={
        "user_email": user.email,
        "is_partner": user.partner_status == "active",
        "partner_tier": user.partner_tier,
        "eligible": signup_count >= PARTNER_JOIN_MIN_SIGNUPS,
        "signup_count": signup_count,
        "paid_count": paid_count,
        "join_min_signups": PARTNER_JOIN_MIN_SIGNUPS,
        "tier2_min_paid": PARTNER_TIER2_MIN_PAID,
        "tier1_pct": PARTNER_TIER1_BPS // 100,
        "tier2_pct": PARTNER_TIER2_BPS // 100,
        "joined": user.partner_waitlist or joined == "1",
        "show_navbar": True,
    })


@app.get("/faq")
async def faq_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_user),
):
    return templates.TemplateResponse(request=request, name="faq.html", context={"show_navbar": True})


@app.post("/partner/waitlist")
async def partner_waitlist(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.partner_waitlist:
        user.partner_waitlist = True
        db.commit()
        track(user.id, "partner_waitlist_joined")
    return RedirectResponse("/partner?joined=1", status_code=303)


@app.post("/partner/join")
async def partner_join(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.partner_status != "active":
        signup_count, paid_count = _partner_counts(user, db)
        if signup_count < PARTNER_JOIN_MIN_SIGNUPS:
            return RedirectResponse("/partner", status_code=303)
        user.partner_status = "active"
        user.partner_tier = 2 if paid_count >= PARTNER_TIER2_MIN_PAID else 1
        db.commit()
        track(user.id, "partner_joined", tier=user.partner_tier)
    return RedirectResponse("/partner/dashboard", status_code=303)


@app.get("/partner/dashboard")
async def partner_dashboard(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if user.partner_status != "active":
        return RedirectResponse("/partner", status_code=303)
    if not user.referral_code:
        user.referral_code = generate_unique_referral_code(db)
        db.commit()

    signup_count, paid_count = _partner_counts(user, db)

    commission_rows = (
        db.query(PartnerCommission, User)
        .join(User, User.id == PartnerCommission.referee_id)
        .filter(PartnerCommission.partner_id == user.id)
        .order_by(PartnerCommission.created_at.desc())
        .all()
    )
    now = datetime.utcnow()
    pending_pence = available_pence = lifetime_pence = 0
    commissions = []
    for c, referee in commission_rows:
        if c.status == CommissionStatus.reversed:
            continue
        lifetime_pence += c.amount_pence
        matured = c.mature_at <= now
        if c.status == CommissionStatus.paid:
            display_status = "paid"
        elif matured:
            available_pence += c.amount_pence
            display_status = "available"
        else:
            pending_pence += c.amount_pence
            display_status = "pending"
        commissions.append({
            "referee_name": referee.username,
            "amount_pence": c.amount_pence,
            "kind": c.kind,
            "status": display_status,
            "date": f"{c.created_at.day} {c.created_at.strftime('%b %Y')}",
            "matures": f"{c.mature_at.day} {c.mature_at.strftime('%b %Y')}" if display_status == "pending" else None,
        })

    return templates.TemplateResponse(request=request, name="partner_dashboard.html", context={
        "referral_code": user.referral_code,
        "partner_tier": user.partner_tier,
        "rate_pct": (PARTNER_TIER2_BPS if user.partner_tier >= 2 else PARTNER_TIER1_BPS) // 100,
        "tier2_pct": PARTNER_TIER2_BPS // 100,
        "signup_count": signup_count,
        "paid_count": paid_count,
        "tier2_min_paid": PARTNER_TIER2_MIN_PAID,
        "hold_days": PARTNER_HOLD_DAYS,
        "pending_pence": pending_pence,
        "available_pence": available_pence,
        "lifetime_pence": lifetime_pence,
        "commissions": commissions,
        "show_navbar": True,
    })


@app.get("/partner/admin")
async def partner_admin(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
):
    partners = db.query(User).filter(User.partner_status == "active").order_by(User.id).all()
    now = datetime.utcnow()
    rows = []
    for p in partners:
        signup_count, paid_count = _partner_counts(p, db)
        rows_c = db.query(PartnerCommission).filter(PartnerCommission.partner_id == p.id).all()
        lifetime = sum(c.amount_pence for c in rows_c if c.status != CommissionStatus.reversed)
        available = sum(
            c.amount_pence for c in rows_c
            if c.status not in (CommissionStatus.paid, CommissionStatus.reversed) and c.mature_at <= now
        )
        pending = sum(
            c.amount_pence for c in rows_c
            if c.status not in (CommissionStatus.paid, CommissionStatus.reversed) and c.mature_at > now
        )
        rows.append({
            "email": p.email,
            "tier": p.partner_tier,
            "signup_count": signup_count,
            "paid_count": paid_count,
            "pending_pence": pending,
            "available_pence": available,
            "lifetime_pence": lifetime,
        })
    return templates.TemplateResponse(request=request, name="partner_admin.html", context={"partners": rows, "show_navbar": True})


@app.get("/admin/usage")
async def admin_usage(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    days: int = 7,
):
    since = datetime.utcnow().date() - timedelta(days=days - 1)
    rows = (
        db.query(UsageDaily, User)
        .join(User, User.id == UsageDaily.user_id)
        .filter(UsageDaily.date >= since)
        .all()
    )
    by_user = {}
    for usage, u in rows:
        total = usage.capture_count + usage.audio_count
        entry = by_user.setdefault(u.id, {
            "id": u.id,
            "email": u.email,
            "account_level": u.account_level.value,
            "is_active": u.is_active,
            "has_sub": bool(u.stripe_sub_id),
            "is_paused": u.account_flag == "paused",
            "period_total": 0,
            "max_day": 0,
        })
        entry["period_total"] += total
        entry["max_day"] = max(entry["max_day"], total)
    entries = sorted(by_user.values(), key=lambda e: e["period_total"], reverse=True)
    return templates.TemplateResponse(request=request, name="admin_usage.html", context={
        "entries": entries,
        "days": days,
        "show_navbar": True,
        "admin_msg": request.query_params.get("admin_msg"),
    })


@app.get("/admin/users")
async def admin_users(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    q: str = "",
):
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.email.ilike(like), User.username.ilike(like)))
    users = query.order_by(User.created_at.desc()).limit(50).all()

    referrer_ids = {u.referred_by_id for u in users if u.referred_by_id}
    referrers = {u.id: u.email for u in db.query(User).filter(User.id.in_(referrer_ids)).all()} if referrer_ids else {}

    entries = [{
        "id": u.id,
        "email": u.email,
        "username": u.username,
        "account_level": u.account_level.value,
        "is_active": u.is_active,
        "has_sub": bool(u.stripe_sub_id),
        "is_paused": u.account_flag == "paused",
        "sessions_remaining": u.sessions_remaining,
        "created_at": u.created_at.strftime("%d %b %Y"),
        "referred_by": referrers.get(u.referred_by_id),
        "partner_status": u.partner_status,
    } for u in users]

    return templates.TemplateResponse(request=request, name="admin_users.html", context={
        "entries": entries,
        "q": q,
        "show_navbar": True,
        "admin_msg": request.query_params.get("admin_msg"),
    })


# Referrers with several signups but zero paid conversions — worth a manual look for
# Sybil/reciprocal-loop farming. Threshold is a starting point, not a hard rule.
_REFERRAL_FLAG_MIN_SIGNUPS = 5


@app.get("/admin/referrals")
async def admin_referrals(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
):
    Referrer = aliased(User)
    Referee = aliased(User)
    rows = (
        db.query(Referral, Referrer, Referee)
        .join(Referrer, Referrer.id == Referral.referrer_id)
        .join(Referee, Referee.id == Referral.referee_id)
        .order_by(Referral.created_at.desc())
        .limit(200)
        .all()
    )
    referrals = [{
        "referrer_email": referrer.email,
        "referee_email": referee.email,
        "status": ref.status.value,
        "intro_credited": ref.intro_credited,
        "sub_credited": ref.sub_credited,
        "created_at": ref.created_at.strftime("%d %b %Y"),
    } for ref, referrer, referee in rows]

    signup_counts = dict(db.query(Referral.referrer_id, func.count(Referral.id)).group_by(Referral.referrer_id).all())
    paid_counts = dict(
        db.query(Referral.referrer_id, func.count(Referral.id))
        .filter(Referral.status == ReferralStatus.subscribed)
        .group_by(Referral.referrer_id)
        .all()
    )
    flagged_ids = [rid for rid, signups in signup_counts.items() if signups >= _REFERRAL_FLAG_MIN_SIGNUPS and paid_counts.get(rid, 0) == 0]
    flagged_users = {u.id: u for u in db.query(User).filter(User.id.in_(flagged_ids)).all()} if flagged_ids else {}
    flagged = sorted([{
        "id": rid,
        "email": flagged_users[rid].email,
        "signups": signup_counts[rid],
        "is_active": flagged_users[rid].is_active,
        "is_paused": flagged_users[rid].account_flag == "paused",
        "has_sub": bool(flagged_users[rid].stripe_sub_id),
    } for rid in flagged_ids if rid in flagged_users], key=lambda f: f["signups"], reverse=True)

    return templates.TemplateResponse(request=request, name="admin_referrals.html", context={
        "referrals": referrals,
        "flagged": flagged,
        "flag_threshold": _REFERRAL_FLAG_MIN_SIGNUPS,
        "show_navbar": True,
        "admin_msg": request.query_params.get("admin_msg"),
    })


def _admin_redirect(return_to: str, msg: str) -> RedirectResponse:
    if not return_to.startswith("/admin/"):
        return_to = "/admin/usage"
    sep = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{sep}{urlencode({'admin_msg': msg})}", status_code=303)


@app.post("/admin/users/{user_id}/ban")
async def admin_ban_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    return_to: str = Form(default="/admin/usage"),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = False
    db.commit()
    send_account_banned_email(target.email)
    track(target.id, "admin_user_banned")
    logger.warning("[admin] banned user=%s", target.email)
    return _admin_redirect(return_to, f"Banned {target.email}")


@app.post("/admin/users/{user_id}/unban")
async def admin_unban_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    return_to: str = Form(default="/admin/usage"),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_active = True
    db.commit()
    send_account_unbanned_email(target.email)
    track(target.id, "admin_user_unbanned")
    logger.warning("[admin] unbanned user=%s", target.email)
    return _admin_redirect(return_to, f"Unbanned {target.email}")


@app.post("/admin/users/{user_id}/pause-subscription")
async def admin_pause_subscription(
    user_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    return_to: str = Form(default="/admin/usage"),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        pause_subscription(target)
    except ValueError:
        return _admin_redirect(return_to, f"{target.email} has no active subscription to pause")
    except stripe.error.StripeError as e:
        logger.error("[admin] failed to pause subscription for %s: %s", target.email, e)
        return _admin_redirect(return_to, f"Stripe error pausing {target.email} — see logs")
    target.account_level = AccountLevel.free
    target.account_flag = "paused"
    target.account_flag_seen = False
    db.commit()
    send_subscription_paused_email(target.email)
    track(target.id, "admin_subscription_paused")
    logger.warning("[admin] paused subscription for user=%s", target.email)
    return _admin_redirect(return_to, f"Paused subscription for {target.email}")


@app.post("/admin/users/{user_id}/resume-subscription")
async def admin_resume_subscription(
    user_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    return_to: str = Form(default="/admin/usage"),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        resume_subscription(target, db)
    except ValueError:
        return _admin_redirect(return_to, f"{target.email} has no active subscription to resume")
    except stripe.error.StripeError as e:
        logger.error("[admin] failed to resume subscription for %s: %s", target.email, e)
        return _admin_redirect(return_to, f"Stripe error resuming {target.email} — see logs")
    target.account_flag = "resumed"
    target.account_flag_seen = False
    db.commit()
    send_subscription_resumed_email(target.email)
    track(target.id, "admin_subscription_resumed")
    logger.warning("[admin] resumed subscription for user=%s", target.email)
    return _admin_redirect(return_to, f"Resumed subscription for {target.email}")


@app.post("/admin/users/{user_id}/warn")
async def admin_warn_user(
    user_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    return_to: str = Form(default="/admin/usage"),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    send_usage_warning_email(target.email)
    track(target.id, "admin_usage_warning_sent")
    logger.info("[admin] usage warning sent to user=%s", target.email)
    return _admin_redirect(return_to, f"Warning emailed to {target.email}")


@app.get("/settings")
async def settings_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    ref_success: Optional[str] = None,
    ref_error: Optional[str] = None,
    offer: Optional[str] = None,
):
    _ensure_api_token(user, db)
    r = request.app.state.redis
    account_flag_notice = user.account_flag if not user.account_flag_seen else None
    if not user.account_flag_seen:
        user.account_flag_seen = True
        db.commit()
    cancel_at = user.sub_cancel_at.strftime("%d %B %Y").lstrip("0") if user.sub_cancel_at else None
    hk = _user_hotkeys(user)
    saved_contexts = {c.slot: c for c in db.query(InterviewContext).filter(InterviewContext.user_id == user.id).all()}
    contexts = [
        {"slot": i, "name": saved_contexts[i].name if i in saved_contexts else "", "text": saved_contexts[i].text if i in saved_contexts else ""}
        for i in range(1, MAX_CONTEXTS_PER_USER + 1)
    ]
    return templates.TemplateResponse(request=request, name="settings.html", context={
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "api_token": user.api_token,
        "base_url": BASE_URL,
        "sub_cancel_at": cancel_at,
        "is_referred": user.referred_by_id is not None,
        "ref_success": ref_success == "1",
        "ref_error_msg": _REFERRAL_ERROR_MESSAGES.get(ref_error),
        "referral_discount_active": bool(STRIPE_REFERRAL_COUPON_ID),
        "offer_claimed": offer == "claimed" and user.retention_offer_claimed,
        "hotkey_capture": hk["capture"],
        "hotkey_audio":   hk["audio"],
        "hotkey_toggle":  hk["toggle"],
        "hotkey_replay":  hk["replay"],
        "hotkey_typing":  hk["typing"],
        "typing_passthrough": user.typing_passthrough,
        "response_style": _user_response_style(user).value,
        "complexity": await get_complexity(r, user.id),
        "replay_enabled": user.replay_enabled,
        "replay_seconds": user.replay_seconds,
        "contexts": contexts,
        "active_context_slot": user.active_context_slot,
        "max_contexts": MAX_CONTEXTS_PER_USER,
        "context_name_max_length": CONTEXT_NAME_MAX_LENGTH,
        "context_text_max_length": CONTEXT_TEXT_MAX_LENGTH,
        "account_flag_notice": account_flag_notice,
        "show_navbar": True,
    })


@app.get("/latest")
async def get_latest(request: Request, user: User = Depends(require_subscription)):
    r = request.app.state.redis
    return {"capture": await get_capture_state(r, user.id), "settings": {"complexity": await get_complexity(r, user.id)}}


@app.get("/screenshot")
async def get_screenshot(user: User = Depends(require_subscription)):
    path = SCREENSHOTS_DIR / f"{user.id}.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No screenshot yet")
    return FileResponse(path, media_type="image/png")


@app.post("/settings/complexity/{direction}")
async def change_complexity(direction: str, request: Request, user: User = Depends(require_subscription)):
    r = request.app.state.redis
    c = await get_complexity(r, user.id)
    if direction == "up":
        c = min(COMPLEXITY_MAX, c + 1)
    elif direction == "down":
        c = max(COMPLEXITY_MIN, c - 1)
    await r.set(_complexity_key(user.id), c)
    await broadcast(r, user.id, "settings", {"complexity": c})
    return {"complexity": c}


# ---------------------------------------------------------------------------
# Capture API — called by browser extension
# ---------------------------------------------------------------------------

@app.post("/api/setup/complete")
async def setup_complete(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.setup_complete = True
    if not user.api_token:
        user.api_token = secrets.token_urlsafe(32)
    db.commit()
    track(user.id, "onboarding_completed")
    return {"status": "ok"}


@app.post("/api/onboarding/mobile-link")
async def onboarding_mobile_link(request: Request, user: User = Depends(get_current_user)):
    r = request.app.state.redis
    token = secrets.token_urlsafe(16)
    await r.setex(f"mobile_login:{token}", 300, str(user.id))
    return {"url": f"{BASE_URL}/mobile-login?token={token}"}


@app.get("/mobile-login")
async def mobile_login(token: str, request: Request, db: Session = Depends(get_db)):
    r = request.app.state.redis
    user_id_str = await r.get(f"mobile_login:{token}")
    if not user_id_str:
        return RedirectResponse("/login?error=link_expired", status_code=303)
    await r.delete(f"mobile_login:{token}")
    user = db.query(User).filter(User.id == int(user_id_str)).first()
    if not user:
        return RedirectResponse("/login?error=link_expired", status_code=303)
    jwt_token = create_token(user.id)
    response = RedirectResponse("/app", status_code=303)
    response.set_cookie("session", jwt_token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return response


@app.post("/api/trial/start")
async def trial_start(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.account_level != AccountLevel.trial:
        raise HTTPException(status_code=400, detail="Not a trial account")
    existing = db.query(InterviewSession).filter(
        InterviewSession.user_id == user.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Trial already used")
    user.setup_complete = True
    session = _get_or_create_session(db, user.id, TRIAL_DURATION)
    db.commit()
    track(user.id, "trial_started")
    return {
        "started_at": session.started_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "seconds_remaining": int(TRIAL_DURATION.total_seconds()),
    }


@app.get("/api/trial/status")
async def trial_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.account_level != AccountLevel.trial:
        return {"is_trial": False}
    session = db.query(InterviewSession).filter(
        InterviewSession.user_id == user.id,
        InterviewSession.ended_at == None,  # noqa: E711
    ).order_by(InterviewSession.started_at.desc()).first()
    if not session:
        return {"is_trial": True, "started": False, "seconds_remaining": 0, "user_id": user.id}
    now = datetime.utcnow()
    remaining = max(0, (session.expires_at - now).total_seconds())
    return {
        "is_trial": True,
        "started": True,
        "seconds_remaining": int(remaining),
        "expired": remaining == 0,
        "user_id": user.id,
    }


@app.post("/api/capture")
async def api_capture(body: CaptureRequest, request: Request, user: User = Depends(get_user_by_token), db: Session = Depends(get_db)):
    r = request.app.state.redis
    await _gate_basic_access(r, user, db)
    await _rate_limit(r, user.id, "capture", cooldown=5, limit=6,
                      cooldown_msg="Capturing too fast — wait 5 seconds between captures",
                      limit_msg="Capture limit reached — you can capture up to 6 times per minute",
                      window_limit=15, window_msg="Capture limit reached — you can capture up to 15 times per 5 minutes")
    _record_usage(db, user.id, "capture")

    if user.account_level == AccountLevel.paid:
        now = datetime.utcnow()
        active = db.query(InterviewSession).filter(
            InterviewSession.user_id == user.id,
            InterviewSession.expires_at > now,
            InterviewSession.ended_at == None,  # noqa: E711
        ).first()
        if not active:
            if user.sessions_remaining <= 0:
                user.account_level = AccountLevel.free
                db.commit()
                raise HTTPException(status_code=403, detail="sessions_exhausted")
            user.sessions_remaining -= 1
            db.commit()
        _get_or_create_session(db, user.id)

    img_b64 = body.image
    if "," in img_b64:
        img_b64 = img_b64.split(",", 1)[1]

    (SCREENSHOTS_DIR / f"{user.id}.png").write_bytes(base64.b64decode(img_b64))

    key = _capture_key(user.id)
    capture_id = await r.hincrby(key, "capture_id", 1)
    await r.hset(key, "monitor", body.monitor)
    await broadcast(r, user.id, "working", {"capture_id": capture_id, "monitor": body.monitor})

    style      = _user_response_style(user)
    complexity = await get_complexity(r, user.id)
    prompt = AI_PROMPT + COMPLEXITY_SUFFIX[complexity] + RESPONSE_STYLE_SUFFIX[style] + _context_suffix(user, db)

    full_text = ""
    async with async_client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    ) as stream:
        async for text in stream.text_stream:
            full_text += text
            await broadcast(r, user.id, "chunk", {"text": text, "capture_id": capture_id})

    ts = time.strftime("%H:%M:%S")
    await r.hset(key, mapping={"analysis": full_text, "timestamp": ts})
    state = await get_capture_state(r, user.id)
    await broadcast(r, user.id, "capture", state)
    track(user.id, "capture_submitted", complexity=complexity)
    return {"status": "ok", "capture_id": capture_id}


@app.post("/api/text-capture")
async def api_text_capture(body: TextCaptureRequest, request: Request, user: User = Depends(get_user_by_token), db: Session = Depends(get_db)):
    r = request.app.state.redis
    await _gate_basic_access(r, user, db)
    await _rate_limit(r, user.id, "capture", cooldown=5, limit=6,
                      cooldown_msg="Sending too fast — wait 5 seconds between submissions",
                      limit_msg="Limit reached — you can submit up to 6 times per minute",
                      window_limit=15, window_msg="Limit reached — you can submit up to 15 times per 5 minutes")
    _record_usage(db, user.id, "capture")

    if user.account_level == AccountLevel.paid:
        now = datetime.utcnow()
        active = db.query(InterviewSession).filter(
            InterviewSession.user_id == user.id,
            InterviewSession.expires_at > now,
            InterviewSession.ended_at == None,  # noqa: E711
        ).first()
        if not active:
            if user.sessions_remaining <= 0:
                user.account_level = AccountLevel.free
                db.commit()
                raise HTTPException(status_code=403, detail="sessions_exhausted")
            user.sessions_remaining -= 1
            db.commit()
        _get_or_create_session(db, user.id)

    await broadcast(r, user.id, "typing-working", {"text": body.text})

    style      = _user_response_style(user)
    complexity = await get_complexity(r, user.id)
    prompt = AI_PROMPT + COMPLEXITY_SUFFIX[complexity] + f"\n\nTyped input: {body.text}" + RESPONSE_STYLE_SUFFIX[style] + _context_suffix(user, db)

    full_text = ""
    async with async_client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            full_text += text
            await broadcast(r, user.id, "chunk", {"text": text})

    await broadcast(r, user.id, "typing-analysis", {
        "input": body.text,
        "analysis": full_text,
        "timestamp": time.strftime("%H:%M:%S"),
    })
    track(user.id, "text_capture_submitted", complexity=complexity)
    return {"status": "ok"}


@app.post("/api/audio-capture")
async def api_audio_capture(
    request: Request,
    audio: UploadFile = File(...),
    user: User = Depends(get_user_by_token),
    db: Session = Depends(get_db),
):
    r = request.app.state.redis
    await _gate_basic_access(r, user, db)
    await _rate_limit(r, user.id, "audio", cooldown=5, limit=10,
                      cooldown_msg="Recording too fast — wait 5 seconds between recordings",
                      limit_msg="Recording limit reached — you can record up to 10 times per minute",
                      window_limit=25, window_msg="Recording limit reached — you can record up to 25 times per 5 minutes")
    _record_usage(db, user.id, "audio")
    await broadcast(r, user.id, "audio-working", {})

    audio_bytes = await audio.read()
    suffix = "." + (audio.filename or "recording.webm").rsplit(".", 1)[-1]
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            transcript = await asyncio.to_thread(
                openai_client.audio.transcriptions.create,
                model="whisper-1",
                file=f,
            )
        transcription_text = transcript.text
        await broadcast(r, user.id, "audio-transcribed", {"transcription": transcription_text})

        style      = _user_response_style(user)
        complexity = await get_complexity(r, user.id)
        prompt = AI_PROMPT + COMPLEXITY_SUFFIX[complexity] + f"\n\nThe interviewer said: {transcription_text}" + RESPONSE_STYLE_SUFFIX[style] + _context_suffix(user, db)
        full_text = ""
        async with async_client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            async for text in stream.text_stream:
                full_text += text
                await broadcast(r, user.id, "chunk", {"text": text})

        await broadcast(r, user.id, "audio-analysis", {
            "transcription": transcription_text,
            "analysis": full_text,
            "timestamp": time.strftime("%H:%M:%S"),
        })
        track(user.id, "audio_capture_submitted")
    except Exception as exc:
        await broadcast(r, user.id, "audio-error", {"message": str(exc)})
        raise HTTPException(status_code=500, detail="Audio processing failed")
    finally:
        os.unlink(tmp_path)

    return {"status": "ok"}


@app.get("/api/me")
async def api_me(request: Request, user: User = Depends(get_user_by_token)):
    r = request.app.state.redis
    return {
        "account_level": user.account_level.value,
        "hotkeys": _user_hotkeys(user),
        "typing_passthrough": user.typing_passthrough,
        "replay": {"enabled": user.replay_enabled, "seconds": user.replay_seconds},
        "complexity": await get_complexity(r, user.id),
        "response_style": _user_response_style(user).value,
    }


class ComplexityRequest(BaseModel):
    value: int = Field(ge=1, le=3)


@app.post("/api/settings/complexity")
async def set_complexity(request: Request, data: ComplexityRequest, user: User = Depends(get_user_by_token)):
    r = request.app.state.redis
    await r.set(_complexity_key(user.id), data.value)
    return {"complexity": data.value}


@app.post("/api/settings/style")
async def set_style_token(data: ResponseStyleRequest, user: User = Depends(get_user_by_token), db: Session = Depends(get_db)):
    user.response_style = data.style
    db.commit()
    return {"status": "ok", "style": data.style.value}


@app.post("/api/settings/hotkeys")
async def save_hotkeys(data: HotkeySettings, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.hotkey_capture = data.capture
    user.hotkey_audio   = data.audio
    user.hotkey_toggle  = data.toggle
    user.hotkey_replay  = data.replay
    user.hotkey_typing  = data.typing
    db.commit()
    return {"status": "ok"}


class PassthroughSetting(BaseModel):
    enabled: bool


@app.post("/api/settings/passthrough")
async def save_passthrough(data: PassthroughSetting, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.typing_passthrough = data.enabled
    db.commit()
    return {"status": "ok"}


@app.post("/api/settings/replay")
async def save_replay(data: ReplaySettings, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.replay_enabled = data.enabled
    user.replay_seconds = data.seconds
    db.commit()
    return {"status": "ok"}


@app.post("/api/settings/response-style")
async def save_response_style(data: ResponseStyleRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.response_style = data.style
    db.commit()
    return {"status": "ok", "style": data.style.value}


@app.post("/api/settings/context")
async def save_context(data: ContextSaveRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = data.name.strip()
    text = data.text.strip()
    ctx = db.query(InterviewContext).filter(
        InterviewContext.user_id == user.id,
        InterviewContext.slot == data.slot,
    ).first()

    if not name and not text:
        if ctx:
            if user.active_context_slot == data.slot:
                user.active_context_slot = None
            db.delete(ctx)
            db.commit()
        return {"status": "ok", "slot": data.slot, "name": "", "text": ""}

    if ctx:
        ctx.name = name
        ctx.text = text
    else:
        db.add(InterviewContext(user_id=user.id, slot=data.slot, name=name, text=text))
    db.commit()
    return {"status": "ok", "slot": data.slot, "name": name, "text": text}


@app.post("/api/settings/context/activate")
async def activate_context(data: ContextActivateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if data.slot is not None:
        ctx = db.query(InterviewContext).filter(
            InterviewContext.user_id == user.id,
            InterviewContext.slot == data.slot,
        ).first()
        if not ctx or not ctx.text:
            raise HTTPException(status_code=400, detail="That context slot is empty.")
    user.active_context_slot = data.slot
    db.commit()
    return {"status": "ok", "slot": data.slot}


@app.post("/api/notify/disabled")
async def notify_disabled(request: Request, user: User = Depends(get_user_by_token)):
    if user.account_level == AccountLevel.free:
        return {"status": "ok"}
    await broadcast(request.app.state.redis, user.id, "disabled", {})
    return {"status": "ok"}


@app.post("/api/notify/enabled")
async def notify_enabled(request: Request, user: User = Depends(get_user_by_token)):
    if user.account_level in (AccountLevel.free, AccountLevel.unlimited):
        return {"status": "ok"}
    await broadcast(request.app.state.redis, user.id, "enabled", {})
    return {"status": "ok"}


@app.post("/api/token/regenerate")
async def regenerate_api_token(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.api_token = secrets.token_urlsafe(32)
    db.commit()
    return {"token": user.api_token}


class AccountUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    username:  Optional[str] = None
    current_password: Optional[str] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password:     str


@app.post("/api/settings/account")
async def update_account(
    body: AccountUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.username and body.username != user.username:
        if not body.current_password or not verify_password(body.current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is required to change your username.")
        if db.query(User).filter(User.username == body.username, User.id != user.id).first():
            raise HTTPException(status_code=400, detail="Username already taken.")
        user.username = body.username
    if body.full_name is not None:
        user.full_name = body.full_name
    db.commit()
    return {"status": "ok"}


@app.post("/api/settings/password")
async def change_password(
    body: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"status": "ok"}


@app.get("/account/delete")
async def account_delete_page(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(request=request, name="account_delete.html", context={
        "has_active_sub": user.account_level == AccountLevel.unlimited and not user.sub_cancel_at,
    })


@app.post("/account/delete/confirm")
async def account_delete_confirm(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    password: str = Form(...),
    reason: str = Form(default=""),
    detail: str = Form(default=""),
):
    if not verify_password(password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect password.")

    if user.stripe_sub_id:
        try:
            cancel_subscription_immediately(user)
        except Exception as e:
            logger.error("[account-delete] failed to cancel stripe sub for %s: %s", user.email, e)

    track(user.id, "account_deleted", reason=reason)
    if reason:
        send_account_deletion_email(user.email, reason, detail)

    user_id = user.id
    db.query(InterviewSession).filter(InterviewSession.user_id == user_id).delete()
    db.query(InterviewContext).filter(InterviewContext.user_id == user_id).delete()
    db.query(Referral).filter(Referral.referrer_id == user_id).delete()
    db.query(Referral).filter(Referral.referee_id == user_id).delete()
    db.query(User).filter(User.referred_by_id == user_id).update({"referred_by_id": None})
    db.delete(user)
    db.commit()

    r = request.app.state.redis
    await r.delete(_capture_key(user_id), _complexity_key(user_id))

    response = RedirectResponse("/login?deleted=1", status_code=303)
    response.delete_cookie("session")
    return response


# ---------------------------------------------------------------------------
# Billing routes
# ---------------------------------------------------------------------------

@app.get("/billing/checkout")
async def billing_checkout(user: User = Depends(get_current_user), db: Session = Depends(get_db), plan: str = "subscription"):
    apply_discount = False
    if plan == "subscription" and user.referred_by_id:
        ref = db.query(Referral).filter(Referral.referee_id == user.id).first()
        if ref and ref.status != ReferralStatus.subscribed:
            apply_discount = True
    url = create_checkout_session(user, db, plan=plan, apply_referral_discount=apply_discount)
    track(user.id, "checkout_initiated", plan=plan)
    return RedirectResponse(url)


@app.get("/billing/cancel")
async def billing_cancel(request: Request, user: User = Depends(get_current_user)):
    hk = _user_hotkeys(user)
    return templates.TemplateResponse(request=request, name="cancel_confirm.html", context={
        "hotkey_capture": hk["capture"],
        "hotkey_toggle":  hk["toggle"],
        "offer_eligible": user.sub_invoice_paid and not user.retention_offer_claimed,
    })


@app.post("/billing/offer")
async def billing_offer(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        apply_retention_coupon(user)
        user.retention_offer_claimed = True
        db.commit()
    except Exception as e:
        logger.error("[retention] failed to apply coupon for %s: %s", user.email, e)
    return RedirectResponse("/settings?offer=claimed", status_code=303)


@app.post("/billing/cancel/confirm")
async def billing_cancel_confirm(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    reason: str = Form(default=""),
    detail: str = Form(default=""),
):
    if not user.stripe_sub_id:
        raise HTTPException(status_code=400, detail="No active subscription found.")
    try:
        cancel_at = cancel_subscription(user)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if cancel_at:
        user.sub_cancel_at = cancel_at
        db.commit()
    track(user.id, "subscription_cancelled", reason=reason)
    if reason:
        send_cancel_feedback_email(user.email, reason, detail, kept=False)
    return RedirectResponse("/settings?cancelled=1", status_code=303)


@app.post("/billing/portal")
@app.get("/billing/portal")
async def billing_portal(user: User = Depends(get_current_user)):
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found.")
    url = create_portal_session(user)
    return RedirectResponse(url, status_code=303)


@app.post("/billing/feedback")
async def billing_feedback(
    user: User = Depends(get_current_user),
    reason: str = Form(default=""),
    detail: str = Form(default=""),
):
    if reason:
        send_cancel_feedback_email(user.email, reason, detail, kept=True)
    return RedirectResponse("/settings", status_code=303)


@app.get("/billing/success")
async def billing_success(request: Request, user: User = Depends(get_optional_user), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse("/login?next=/billing/success", status_code=302)
    db.refresh(user)
    return templates.TemplateResponse(request=request, name="billing_success.html", context={})


@app.get("/api/billing/status")
async def billing_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.refresh(user)
    return {
        "account_level": user.account_level.value,
        "sessions_remaining": user.sessions_remaining,
        "intro_declined": user.intro_declined,
    }


@app.post("/billing/webhook")
async def billing_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        handle_webhook_event(payload, sig, db)
    except Exception as e:
        logger.exception("[webhook] unhandled error processing event")
        raise HTTPException(status_code=400, detail=str(e))
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

@app.get("/stream")
async def stream(request: Request, user: User = Depends(require_subscription)):
    r = request.app.state.redis
    state = await get_capture_state(r, user.id)
    settings_payload = json.dumps({"type": "settings", "complexity": await get_complexity(r, user.id)})
    pubsub = r.pubsub()
    await pubsub.subscribe(_events_channel(user.id))

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'capture', **state})}\n\n"
            yield f"data: {settings_payload}\n\n"
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    yield f"data: {msg['data']}\n\n"
        finally:
            await pubsub.unsubscribe(_events_channel(user.id))
            await pubsub.aclose()

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    if RELOAD:
        # This repo lives on a 9p-mounted WSL2 drive (/mnt/d/...), where inotify events
        # don't reliably fire — the same constraint noted in database.py for SQLite locking.
        # watchfiles (uvicorn's --reload backend) needs polling mode here or it silently
        # never restarts on file changes.
        os.environ.setdefault("WATCHFILES_FORCE_POLLING", "true")
        uvicorn.run("server:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)
    else:
        uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
