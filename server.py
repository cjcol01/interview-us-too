# startup profiling: capture the very first instant of the process (before any other
# import) so the [startup] logs can also show how long stdlib imports themselves took —
# on a slow filesystem even those add up. See STARTUP_PERF.md.
import time as _time
_PROC_T0 = _time.perf_counter()

import asyncio
import base64
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from urllib.parse import urlencode

# --- startup profiling (see STARTUP_PERF.md) — capture the clock *before* the heavy
# third-party imports below so we can measure how long they take. On a slow filesystem
# (e.g. a WSL2 9p-mounted repo/venv) importing anthropic+openai reads ~2700 small module
# files and this phase balloons; the [startup] logs below make that visible per boot. ---
_BOOT_T0 = time.perf_counter()

import anthropic  # noqa: E402
import httpx
import redis.asyncio as aioredis
import redis.exceptions as redis_exceptions
import requests
import stripe
import uvicorn
from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import jwt as jose_jwt
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel, Field
from sqlalchemy import and_, false, func, or_, text, true
from sqlalchemy.orm import Session, aliased
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from analytics import identify, logger, track
from auth import create_token, decode_user_id, generate_unique_referral_code, generate_unique_username, get_current_user, get_optional_user, get_user_by_token, hash_password, validate_password, verify_password
from billing import apply_retention_coupon, cancel_subscription, cancel_subscription_immediately, create_checkout_session, create_portal_session, handle_webhook_event, pause_subscription, resume_subscription
from config import AI_PROMPT, ANTHROPIC_API_KEY, APP_VERSION, AUTHOR_PASSWORD, BASE_URL, DEEPGRAM_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_OAUTH_ENABLED, LANDING_PROD, OPENAI_API_KEY, PARTNER_HOLD_DAYS, PARTNER_JOIN_MIN_SIGNUPS, PARTNER_TIER1_BPS, PARTNER_TIER2_BPS, PARTNER_TIER2_MIN_PAID, POSTHOG_API_KEY, RELOAD, REDIS_URL, RESEND_API_KEY, SERVER_HOST, SERVER_PORT, SIDELOAD_ENABLED, SIDELOAD_ZIP_URL, SKIP_EMAIL_VERIFICATION, STRIPE_REFERRAL_COUPON_ID, STRIPE_SECRET_KEY, STRIPE_SESSIONS_PACK_PRICE_ID, STRIPE_SESSIONS_PRICE_ID, STRIPE_SUB_PRICE_ID, STRIPE_SUB_PRICE_PENCE, STRIPE_WEBHOOK_SECRET
from mailer import send_account_banned_email, send_account_deletion_email, send_account_unbanned_email, send_announcement_email, send_cancel_feedback_email, send_expiry_reminder_email, send_low_sessions_email, send_password_reset_email, send_subscription_paused_email, send_subscription_resumed_email, send_usage_warning_email, send_verification_email
from database import DATA_DIR, SessionLocal, get_db, init_db
from metrics import EMAIL_FAIL_PREFIX, HTTP_5XX_PREFIX, METRIC_TTL_SECONDS, hourly_bucket_key
from models import AccountLevel, Announcement, AnnouncementDismissal, CommissionStatus, InterviewContext, InterviewSession, PartnerCommission, Referral, ReferralStatus, ResponseStyle, UsageDaily, User

# --- startup profiling: log where boot time goes so slow environments (e.g. a WSL2
# 9p-mounted repo) can be diagnosed straight from the logs. See STARTUP_PERF.md. ---
_BOOT_LAST = _BOOT_T0


def _boot_mark(label: str) -> None:
    global _BOOT_LAST
    now = time.perf_counter()
    logger.info("[startup] %-24s +%5.2fs (since proc start %5.2fs)", label, now - _BOOT_LAST, now - _PROC_T0)
    _BOOT_LAST = now


logger.info("[startup] %-24s +%5.2fs (since proc start %5.2fs)", "stdlib imports", _BOOT_T0 - _PROC_T0, _BOOT_T0 - _PROC_T0)
_boot_mark("heavy imports loaded")

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


def _active_announcement_for(user: User) -> Optional[Announcement]:
    """Site-wide announcement banner (see admin_announcements route below). Jinja2 context
    processors run synchronously, so this opens its own short-lived session rather than
    reusing a route's async-flavoured db dependency — same pattern _optional_user_from_request
    already uses one line up. Announcements tables stay small (handful of rows), so the
    unindexed scan here is cheap; no caching layer for what's normally a 0-or-1-row lookup."""
    db = SessionLocal()
    try:
        candidates = (
            db.query(Announcement)
            .filter(Announcement.in_app_active == True)  # noqa: E712
            .order_by(Announcement.created_at.desc())
            .limit(10)
            .all()
        )
        for ann in candidates:
            if not _user_in_segment(db, user, ann.segment, ann.target_email):
                continue
            dismissed = db.query(AnnouncementDismissal).filter(
                AnnouncementDismissal.announcement_id == ann.id,
                AnnouncementDismissal.user_id == user.id,
            ).first()
            if not dismissed:
                return ann
        return None
    finally:
        db.close()


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
        "active_announcement": _active_announcement_for(user) if user else None,
    }


templates = Jinja2Templates(directory="templates", context_processors=[_template_globals])
templates.env.globals["POSTHOG_KEY"] = POSTHOG_API_KEY
templates.env.globals["POSTHOG_HOST"] = os.getenv("POSTHOG_HOST", "https://eu.i.posthog.com")
templates.env.globals["APP_VERSION"] = APP_VERSION
SCREENSHOTS_DIR = Path("screenshots")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _boot_mark("lifespan start")
    init_db()
    _boot_mark("init_db() done")
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    app.state.started_at = datetime.utcnow()
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
        _boot_mark("redis reachable")
    logger.info("[ready] http://localhost:%d", SERVER_PORT)
    _boot_mark("READY (total boot)")
    if os.getenv("TESTING") != "1":
        # The openai SDK pays a one-time ~5s warm-up tax on its first real API call per
        # process (httpx/transport init — confirmed via timing, not network latency; a
        # second call in the same process drops to ~400ms). Left alone, that cost shows up
        # as a misleadingly slow first "Run deep checks" click — pay it here instead, in the
        # background, so it's already absorbed by the time anyone looks at /admin/health.
        async def _warm_openai():
            try:
                await asyncio.to_thread(_check_openai)
            except Exception:
                pass
        app.state.openai_warmup_task = asyncio.create_task(_warm_openai())
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
    try:
        response = await call_next(request)
    except Exception:
        # Starlette hoists the handler registered for the base Exception type (ours, above)
        # to the outermost ServerErrorMiddleware — which sits above this middleware and always
        # re-raises after building the 500 response, so an unhandled exception never comes back
        # to us as a response object here; it comes back as a raised exception. Count it as a
        # 5xx here, then re-raise so ServerErrorMiddleware still builds the actual response.
        await _incr_hourly_metric(request.app.state.redis, HTTP_5XX_PREFIX)
        raise
    ms = int((time.time() - start) * 1000)
    logger.info("%s %s → %d (%dms) user=%s", request.method, request.url.path, response.status_code, ms, user_id)
    if response.status_code >= 500:
        # A route that returns (rather than raises) a 5xx response takes this path instead.
        await _incr_hourly_metric(request.app.state.redis, HTTP_5XX_PREFIX)
    return response


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    # user= identifies who triggered it. The query string disambiguates routes that serve
    # several distinct UI actions off the same path (e.g. /billing/checkout?plan=... covers
    # both "Top up sessions" and "Upgrade to Unlimited") without needing to log request bodies,
    # which for other routes could mean passwords or multi-MB base64 screenshot/audio payloads.
    token = request.cookies.get("session")
    user_id = decode_user_id(token) if token else None
    path = f"{request.url.path}?{request.url.query}" if request.url.query else request.url.path
    logger.exception("Unhandled exception on %s %s (user=%s)", request.method, path, user_id)
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
openai_async_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

_OPENAI_VISION_MODEL = "gpt-5.4"


async def _stream_ai_response(r, user_id: int, prompt: str, img_b64: Optional[str] = None, capture_id: Optional[int] = None, history: Optional[list] = None) -> str:
    """Streams Claude's reply chunk-by-chunk via SSE broadcast (the normal path). If Claude
    errors — outage, rate limit, timeout — transparently fails over to OpenAI's vision model,
    streamed the same way, so a failover reply still trickles in token-by-token instead of
    popping in all at once.

    `history` is an optional list of {"role", "content"} turns from the bounded rolling
    window (see _load_history_messages) — prepended ahead of the current turn for both
    providers. Only the current (final) turn ever carries an image or the full prompt
    text; historical turns are lightweight text only, so a past screenshot can never be
    resent."""
    content = ([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}}] if img_b64 else []) + [{"type": "text", "text": prompt}]
    try:
        full_text = ""
        async with async_client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=(history or []) + [{"role": "user", "content": content}],
        ) as stream:
            async for text in stream.text_stream:
                full_text += text
                payload = {"text": text, **({"capture_id": capture_id} if capture_id is not None else {})}
                await broadcast(r, user_id, "chunk", payload)
        return full_text
    except Exception as e:
        logger.error("[ai] Claude failed, failing over to OpenAI: %s", e)
        openai_content = ([{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}] if img_b64 else []) + [{"type": "text", "text": prompt}]
        full_text = ""
        stream = await openai_async_client.chat.completions.create(
            model=_OPENAI_VISION_MODEL,
            max_completion_tokens=1024,
            messages=(history or []) + [{"role": "user", "content": openai_content}],
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if not delta:
                continue
            full_text += delta
            payload = {"text": delta, **({"capture_id": capture_id} if capture_id is not None else {})}
            await broadcast(r, user_id, "chunk", payload)
        return full_text


_AUDIO_MIME_TYPES = {
    ".webm": "audio/webm", ".wav": "audio/wav", ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".mp4": "audio/mp4",
}


def _deepgram_transcribe(audio_bytes: bytes, suffix: str) -> str:
    resp = requests.post(
        "https://api.deepgram.com/v1/listen",
        headers={
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": _AUDIO_MIME_TYPES.get(suffix, "audio/webm"),
        },
        params={"model": "nova-2"},
        data=audio_bytes,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


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
    return (
        "\n\nBackground context about this candidate/interview, for reference only. "
        "Only bring this up or factor it into your answer if it's directly relevant to "
        f"the specific question asked — otherwise ignore it and answer normally:\n{ctx.text}"
    )


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

# Bounded rolling-window conversation history, shared across all three capture
# endpoints (screenshot/text/audio). Named "history", not "context", to avoid
# confusion with the separate, DB-backed InterviewContext ("interview context"
# tab) feature. Both knobs below are safe to tune by editing the constant alone:
# HISTORY_TOPIC_GAP_SECONDS is a plain comparison; HISTORY_MAX_EXCHANGES <= 0
# is explicitly guarded in _append_history (see comment there) so "0" cleanly
# reverts to today's fully-stateless behavior instead of hitting Redis's
# LTRIM "-0 is just 0" footgun.
HISTORY_MAX_EXCHANGES      = 5
HISTORY_REPLY_MAX_CHARS    = 1600   # ~400 tokens
HISTORY_QUESTION_MAX_CHARS = 1600
HISTORY_TOPIC_GAP_SECONDS  = 300    # ~5 min — past this, treat it as a new topic
SCREENSHOT_PLACEHOLDER     = "[Screenshot capture]"

def _history_key(uid: int) -> str: return f"user:{uid}:history"


async def get_capture_state(r, user_id: int) -> dict:
    data = await r.hgetall(_capture_key(user_id))
    merged = {**_CAPTURE_DEFAULTS, **data}
    merged["capture_id"] = int(merged["capture_id"])
    return merged


async def get_complexity(r, user_id: int) -> int:
    val = await r.get(_complexity_key(user_id))
    return int(val) if val is not None else 2


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n]


def _history_ttl(account_level) -> int:
    return int(TRIAL_DURATION.total_seconds()) if account_level == AccountLevel.trial else int(SESSION_DURATION.total_seconds())


async def _load_history_messages(r, user_id: int) -> list:
    """Reconstructs the rolling-window history as alternating user/assistant
    turns (oldest first). Returns [] if there's no history, if the most recent
    exchange is older than HISTORY_TOPIC_GAP_SECONDS (treated as a new topic —
    the caller still appends the new exchange afterward), or on any Redis error
    (never fail a capture over the history feature)."""
    try:
        raw = await r.lrange(_history_key(user_id), 0, -1)
        if not raw:
            return []
        entries = [json.loads(item) for item in raw]
        if time.time() - entries[-1]["ts"] > HISTORY_TOPIC_GAP_SECONDS:
            return []
        messages = []
        for entry in entries:
            messages.append({"role": "user", "content": entry["q"]})
            messages.append({"role": "assistant", "content": entry["a"]})
        return messages
    except Exception as e:
        logger.error("[history] failed to load history for user %s: %s", user_id, e)
        return []


async def _append_history(r, user_id: int, src: str, question: str, reply: str, account_level) -> None:
    """Appends one completed exchange to the rolling window, trimmed to
    HISTORY_MAX_EXCHANGES. No-op if HISTORY_MAX_EXCHANGES <= 0 (see the
    constant's doc comment) or on any Redis error."""
    if HISTORY_MAX_EXCHANGES <= 0:
        return
    try:
        key = _history_key(user_id)
        entry = json.dumps({
            "src": src,
            "q": _truncate(question, HISTORY_QUESTION_MAX_CHARS),
            "a": _truncate(reply, HISTORY_REPLY_MAX_CHARS),
            "ts": time.time(),
        })
        await r.rpush(key, entry)
        await r.ltrim(key, -HISTORY_MAX_EXCHANGES, -1)
        await r.expire(key, _history_ttl(account_level))
    except Exception as e:
        logger.error("[history] failed to append history for user %s: %s", user_id, e)


async def _clear_history(r, user_id: int) -> None:
    try:
        await r.delete(_history_key(user_id))
    except Exception as e:
        logger.error("[history] failed to clear history for user %s: %s", user_id, e)


def _get_or_create_session(db: Session, user_id: int, duration: timedelta = SESSION_DURATION) -> tuple:
    """Returns (session, created) — `created` is True only when a brand-new
    InterviewSession row was inserted (no active session existed), False when
    an existing active session was reused. Callers use this to know when it's
    safe to clear session-scoped Redis state (like rolling history) without
    wiping context from a session still in progress."""
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
        return session, True
    return session, False


def require_subscription(user: User = Depends(get_current_user)) -> User:
    if user.account_level == AccountLevel.free:
        raise HTTPException(status_code=403, detail="Subscription required")
    return user


def _client_ip(request: Request) -> str:
    """Best-effort real client IP, trusting Cloudflare/reverse-proxy headers over the raw
    socket peer (which behind a proxy is just the proxy's own address)."""
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _rate_limit(r, user_id: int | str, endpoint: str, cooldown: int, limit: int,
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
        def _check_trial():
            now = datetime.utcnow()
            active = db.query(InterviewSession).filter(
                InterviewSession.user_id == user.id,
                InterviewSession.expires_at > now,
                InterviewSession.ended_at == None,  # noqa: E711
            ).first()
            if not active:
                user.account_level = AccountLevel.free
                db.commit()
            return active

        active = await run_in_threadpool(_check_trial)
        if not active:
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
def favicon():
    return FileResponse("static/favicon.svg", media_type="image/svg+xml")


@app.get("/502", include_in_schema=False)
def preview_502():
    # Dev-only preview of the static page the reverse proxy serves when the app
    # itself is down (see static/502.html) — served at 200 here since the app
    # answering at all means there's no real gateway error to report.
    return FileResponse("static/502.html", media_type="text/html")


# Auth routes
# ---------------------------------------------------------------------------

@app.get("/login")
def login_page(request: Request, user: Optional[User] = Depends(get_optional_user), next: Optional[str] = None):
    if user:
        return RedirectResponse(next or "/app")
    return templates.TemplateResponse(request=request, name="login.html", context={"google_enabled": GOOGLE_OAUTH_ENABLED})


@app.post("/auth/login")
async def auth_login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    r = request.app.state.redis
    # IP-based: a loose backstop against one connection spraying guesses across many
    # accounts. No cooldown, since a shared IP (uni halls, office, CGNAT) can have several
    # different real people submitting logins within the same second.
    await _rate_limit(r, _client_ip(request), "login_ip", cooldown=0, limit=20,
                      limit_msg="Too many login attempts from this connection — try again in a minute",
                      window_limit=60, window_seconds=300,
                      window_msg="Too many login attempts from this connection — try again in a few minutes")
    # Username-based: the real defense against brute-forcing one account — doesn't care how
    # many other people share your IP, and also catches attempts spread across many IPs.
    await _rate_limit(r, body.username.lower(), "login_user", cooldown=2, limit=6,
                      cooldown_msg="Too many attempts — wait a moment before trying again",
                      limit_msg="Too many attempts on this account — try again in a minute",
                      window_limit=15, window_seconds=900,
                      window_msg="Too many attempts on this account — try again later")
    def _authenticate():
        user = db.query(User).filter(User.username == body.username).first()
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password.")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="This account has been suspended. Contact support if you think this is a mistake.")
        user.last_login = datetime.utcnow()
        db.commit()
        return user

    user = await run_in_threadpool(_authenticate)
    track(user.id, "login")

    token = create_token(user.id)
    response = JSONResponse({"status": "ok", "username": user.username})
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return response


@app.post("/auth/register")
async def auth_register(
    body: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
    ref: Optional[str] = Cookie(default=None),
):
    r = request.app.state.redis
    # No per-identity axis to split on for signup (that's what's being created), so this stays
    # purely IP-based — kept loose enough that a shared network signing up together (uni halls,
    # a class) doesn't get caught, while still bounding a scripted mass-signup bot.
    await _rate_limit(r, _client_ip(request), "register", cooldown=1, limit=10,
                      cooldown_msg="Too many attempts — wait a moment before trying again",
                      limit_msg="Too many signups from this connection — try again in a minute",
                      window_limit=25, window_msg="Too many signups from this connection — try again later")
    def _register():
        if db.query(User).filter(User.username == body.username).first():
            raise HTTPException(status_code=400, detail="Username already taken.")
        if db.query(User).filter(User.email == body.email).first():
            raise HTTPException(status_code=400, detail="Email already registered.")
        password_error = validate_password(body.password)
        if password_error:
            raise HTTPException(status_code=400, detail=password_error)

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
        return user

    user = await run_in_threadpool(_register)
    identify(user.id, user.email, user.full_name, user.account_level.value)
    track(user.id, "signup", referred=bool(ref))

    token = create_token(user.id)
    response = JSONResponse({"status": "ok", "username": user.username})
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    response.delete_cookie("ref")
    return response


async def _google_exchange_claims(code: str) -> dict:
    """Exchanges an OAuth authorization code for the caller's Google identity. Split out as
    its own function (rather than inlined in the callback route) so tests can monkeypatch it
    instead of hitting Google's real token endpoint."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": f"{BASE_URL}/auth/google/callback",
                "grant_type": "authorization_code",
            },
        )
    resp.raise_for_status()
    id_token = resp.json()["id_token"]
    # Signature not verified: this id_token just arrived directly from Google over TLS via a
    # server-to-server exchange (never passed through the browser), so there's no untrusted
    # party in a position to have forged it.
    claims = jose_jwt.get_unverified_claims(id_token)
    return {
        "sub": claims["sub"],
        "email": claims.get("email", ""),
        "email_verified": claims.get("email_verified") in (True, "true"),
        "name": claims.get("name") or claims.get("email", "").split("@")[0],
    }


@app.get("/auth/google")
async def auth_google_start(request: Request, next: Optional[str] = None, ref: Optional[str] = Cookie(default=None)):
    if not GOOGLE_OAUTH_ENABLED:
        raise HTTPException(status_code=404)
    r = request.app.state.redis
    state = secrets.token_urlsafe(24)
    # Short-lived server-side stash of the state token — same pattern as the mobile-login
    # token (see onboarding_mobile_link below) — doubles as CSRF protection for the callback.
    await r.setex(f"oauth:google:{state}", 600, json.dumps({"next": next, "ref": ref}))
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{BASE_URL}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}", status_code=302)


@app.get("/auth/google/callback")
async def auth_google_callback(
    request: Request,
    db: Session = Depends(get_db),
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    if not GOOGLE_OAUTH_ENABLED:
        raise HTTPException(status_code=404)
    if error or not code or not state:
        return RedirectResponse("/login?error=oauth_failed", status_code=303)

    r = request.app.state.redis
    stashed = await r.get(f"oauth:google:{state}")
    if not stashed:
        return RedirectResponse("/login?error=oauth_failed", status_code=303)
    await r.delete(f"oauth:google:{state}")
    stashed = json.loads(stashed)
    next_url, ref = stashed.get("next"), stashed.get("ref")

    try:
        claims = await _google_exchange_claims(code)
    except Exception:
        logger.exception("Google OAuth token exchange failed")
        return RedirectResponse("/login?error=oauth_failed", status_code=303)

    if not claims["email"]:
        return RedirectResponse("/login?error=oauth_failed", status_code=303)

    def _resolve_user():
        user = db.query(User).filter(User.google_id == claims["sub"]).first()
        if user:
            return user, False

        existing = db.query(User).filter(User.email == claims["email"]).first()
        if existing:
            existing.google_id = claims["sub"]
            if not existing.email_verified:
                # This account's email was never proven — Google's proof of ownership wins.
                # Verify it and invalidate whatever password is on the account: otherwise
                # someone could pre-register a victim's email with a password, then simply
                # keep using that password after the victim later links their real Google
                # account (account pre-hijacking).
                existing.email_verified = True
                existing.password_hash = hash_password(secrets.token_urlsafe(32))
            db.commit()
            return existing, False

        username = generate_unique_username(db, claims["email"].split("@")[0])
        new_user = User(
            username=username,
            email=claims["email"],
            full_name=claims["name"],
            password_hash=hash_password(secrets.token_urlsafe(32)),  # unused — Google-only account
            account_level=AccountLevel.trial,
            email_verified=True,
            google_id=claims["sub"],
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        new_user.referral_code = generate_unique_referral_code(db)
        if ref:
            referrer = db.query(User).filter(User.referral_code == ref).first()
            if referrer and referrer.id != new_user.id:
                new_user.referred_by_id = referrer.id
                db.add(Referral(referrer_id=referrer.id, referee_id=new_user.id))
        db.commit()
        return new_user, True

    user, is_new = await run_in_threadpool(_resolve_user)
    if not user.is_active:
        return RedirectResponse("/login?error=account_suspended", status_code=303)

    if is_new:
        identify(user.id, user.email, user.full_name, user.account_level.value)
        track(user.id, "signup", referred=bool(ref), method="google")
    else:
        user.last_login = datetime.utcnow()
        db.commit()
        track(user.id, "login", method="google")

    token = create_token(user.id)
    response = RedirectResponse(next_url or "/app", status_code=303)
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    if ref:
        response.delete_cookie("ref")
    return response


@app.post("/auth/resend-verification")
async def resend_verification(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.email_verified:
        raise HTTPException(status_code=400, detail="Email already verified.")
    r = request.app.state.redis
    await _rate_limit(r, user.id, "resend_verification", cooldown=30, limit=3,
                      cooldown_msg="Please wait before requesting another email",
                      limit_msg="Too many requests — try again in a few minutes",
                      window_limit=3, window_seconds=600,
                      window_msg="Too many requests — try again in a few minutes")
    def _resend():
        user.verify_token = secrets.token_urlsafe(32)
        db.commit()
        send_verification_email(user.email, user.verify_token)

    await run_in_threadpool(_resend)
    return {"status": "ok"}


@app.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.verify_token == token).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link.")
    user.email_verified = True
    user.verify_token = None
    db.commit()
    track(user.id, "email_verified", account_level=user.account_level.value)
    if user.account_level == AccountLevel.trial:
        return RedirectResponse("/welcome")
    return RedirectResponse("/app")


@app.get("/forgot-password")
def forgot_password_page(request: Request, user: Optional[User] = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/app")
    return templates.TemplateResponse(request=request, name="forgot_password.html", context={})


@app.post("/auth/forgot-password")
async def auth_forgot_password(body: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)):
    r = request.app.state.redis
    # Email-based: caps how many reset emails one target inbox can be flooded with, regardless
    # of how many different IPs the requests come from.
    await _rate_limit(r, body.email.lower(), "forgot_password_email", cooldown=30, limit=3,
                      cooldown_msg="Please wait before requesting another email",
                      limit_msg="Too many requests for this email — try again in a few minutes",
                      window_limit=3, window_seconds=600,
                      window_msg="Too many requests for this email — try again in a few minutes")
    # IP-based: loose backstop against one connection spraying requests across many target
    # emails. No cooldown — a shared IP can have several different real people at once.
    await _rate_limit(r, _client_ip(request), "forgot_password_ip", cooldown=0, limit=10,
                      limit_msg="Too many requests from this connection — try again in a minute",
                      window_limit=30, window_seconds=300,
                      window_msg="Too many requests from this connection — try again in a few minutes")
    def _maybe_reset():
        user = db.query(User).filter(User.email == body.email, User.is_active == True).first()
        if user:
            user.reset_token = secrets.token_urlsafe(32)
            user.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
            db.commit()
            send_password_reset_email(user.email, user.reset_token)

    await run_in_threadpool(_maybe_reset)
    # Always return ok — never reveal whether the email is registered
    return {"status": "ok"}


@app.get("/reset-password")
def reset_password_page(request: Request, token: str = "", db: Session = Depends(get_db)):
    # Pre-validate so we can show a useful error on stale/bad links
    user = db.query(User).filter(User.reset_token == token).first() if token else None
    invalid = not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow()
    return templates.TemplateResponse(
        request=request,
        name="reset_password.html",
        context={"token": token, "invalid": invalid},
    )


@app.post("/auth/reset-password")
def auth_reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == body.token).first()
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")
    password_error = validate_password(body.new_password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)
    user.password_hash = hash_password(body.new_password)
    user.reset_token = None
    user.reset_token_expiry = None
    db.commit()
    track(user.id, "password_reset")
    return {"status": "ok"}


@app.post("/auth/logout")
@app.get("/auth/logout")
def auth_logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response


# ---------------------------------------------------------------------------
# App routes
# ---------------------------------------------------------------------------

@app.get("/")
def landing(request: Request, user: Optional[User] = Depends(get_optional_user)):
    template = "landing.html" if LANDING_PROD else "landing_prep.html"
    ctx = {"show_navbar": True, "show_landing_links": True}
    return templates.TemplateResponse(request=request, name=template, context=ctx)


@app.get("/app")
def index(request: Request, user: User = Depends(require_user)):
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


@app.get("/welcome")
def welcome_page(request: Request, user: User = Depends(require_user)):
    if not user.email_verified:
        return RedirectResponse("/verify-pending")
    if user.account_level != AccountLevel.trial:
        return RedirectResponse("/app")
    track(user.id, "welcome_viewed")
    return templates.TemplateResponse(request=request, name="welcome.html", context={
        **_user_hotkeys(user),
    })


@app.get("/onboarding")
def onboarding_page(
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
        "sideload_enabled": SIDELOAD_ENABLED,
    })


@app.get("/verify-pending")
def verify_pending(request: Request, user: User = Depends(require_user)):
    if user.email_verified:
        return RedirectResponse("/app")
    return templates.TemplateResponse(request=request, name="verify_pending.html", context={
        "email": user.email,
    })


@app.get("/trial-end")
def trial_end(request: Request, user: User = Depends(require_user)):
    hk = _user_hotkeys(user)
    return templates.TemplateResponse(request=request, name="trial_end.html", context={
        "hotkey_capture": hk["capture"],
        "hotkey_audio":   hk["audio"],
        "hotkey_toggle":  hk["toggle"],
        "hotkey_replay":  hk["replay"],
        "show_navbar": True,
    })


@app.get("/pricing")
def pricing_page(request: Request, user: Optional[User] = Depends(get_optional_user)):
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

_AUTHOR_MAX_FAILS = 5
_AUTHOR_LOCKOUT_SECONDS = 15 * 60

async def _require_author(
    request: Request,
    user: Optional[User] = Depends(get_optional_user),
    credentials: Optional[HTTPBasicCredentials] = Depends(_basic),
):
    if user and user.username == _ADMIN_USERNAME:
        return

    r = request.app.state.redis
    fail_key = f"rl:author_fail:{_client_ip(request)}"
    unauthed = HTTPException(status_code=401, headers={"WWW-Authenticate": 'Basic realm="author"'})

    fails = await r.get(fail_key)
    if fails and int(fails) >= _AUTHOR_MAX_FAILS:
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts — try again later.",
            headers={"WWW-Authenticate": 'Basic realm="author"'},
        )

    if (
        credentials
        and AUTHOR_PASSWORD
        and secrets.compare_digest(credentials.username.encode(), _ADMIN_USERNAME.encode())
        and secrets.compare_digest(credentials.password.encode(), AUTHOR_PASSWORD.encode())
    ):
        if fails:
            await r.delete(fail_key)
        return

    # Only count actual (wrong) credential submissions against the lockout — not the
    # first, credential-less request that's a normal part of the Basic Auth handshake.
    if credentials is not None:
        new_fails = await r.incr(fail_key)
        if new_fails == 1:
            await r.expire(fail_key, _AUTHOR_LOCKOUT_SECONDS)
    raise unauthed

@app.get("/verify-author")
def author_page(request: Request, _: None = Depends(_require_author)):
    return templates.TemplateResponse(request=request, name="author.html", context={"show_navbar": True})


@app.get("/r/{code}")
def referral_redirect(
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
def referral_page(
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
def apply_referral_code(
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
def partner_page(
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
def faq_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_user),
):
    return templates.TemplateResponse(request=request, name="faq.html", context={"show_navbar": True})


@app.get("/install-manual")
def install_manual_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_user),
):
    if not SIDELOAD_ENABLED:
        raise HTTPException(status_code=404)
    same_origin_zip_url = f"{BASE_URL}/static/extension/interviewace-extension.zip"
    return templates.TemplateResponse(request=request, name="install_manual.html", context={
        "show_navbar": True,
        "zip_url": SIDELOAD_ZIP_URL,
        "mirror_zip_url": same_origin_zip_url,
    })


@app.post("/partner/waitlist")
def partner_waitlist(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.partner_waitlist:
        user.partner_waitlist = True
        db.commit()
        track(user.id, "partner_waitlist_joined")
    return RedirectResponse("/partner?joined=1", status_code=303)


@app.post("/partner/join")
def partner_join(
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
def partner_dashboard(
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
def partner_admin(
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


# ---------------------------------------------------------------------------
# Admin home — a hub linking to the other admin pages, with a "worth a look" strip at
# the top that only lists what's actually notable right now (nothing on a quiet day).
# Only cheap, local checks run here (no deep/external calls) since this is the page
# every admin visit lands on first.
# ---------------------------------------------------------------------------

@app.get("/admin")
async def admin_home(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
):
    r = request.app.state.redis
    redis_check = await _check_redis(r)
    webhook_check = await _last_webhook_status(r)
    disk_check = _check_disk()
    missing_config = [c["name"] for c in _config_status() if not c["configured"]]

    def _load_counts():
        db_check = _check_database(db)
        now = datetime.utcnow()
        total_users = db.query(User).count()
        new_7d = db.query(User).filter(User.created_at >= now - timedelta(days=7)).count()
        banned_count = db.query(User).filter(User.is_active == False).count()  # noqa: E712
        pending_cancellations = db.query(User).filter(User.sub_cancel_at.isnot(None)).count()
        active_subs = db.query(User).filter(
            User.account_level == AccountLevel.unlimited, User.stripe_sub_id.isnot(None)
        ).count()
        flagged_referrers = _flagged_referrer_count(db)
        active_announcements = db.query(Announcement).filter(Announcement.in_app_active == True).count()  # noqa: E712
        usage_today = db.query(
            func.coalesce(func.sum(UsageDaily.capture_count), 0), func.coalesce(func.sum(UsageDaily.audio_count), 0)
        ).filter(UsageDaily.date == now.date()).first()
        return (db_check, total_users, new_7d, banned_count, pending_cancellations,
                active_subs, flagged_referrers, active_announcements, usage_today)

    (db_check, total_users, new_7d, banned_count, pending_cancellations,
     active_subs, flagged_referrers, active_announcements, usage_today) = await run_in_threadpool(_load_counts)

    alerts = []
    if not redis_check["ok"]:
        alerts.append({"level": "danger", "text": f"Redis unreachable — {redis_check['detail']}", "href": "/admin/health"})
    if not db_check["ok"]:
        alerts.append({"level": "danger", "text": f"Database check failed — {db_check['detail']}", "href": "/admin/health"})
    if disk_check["ok"] is False:
        alerts.append({"level": "danger", "text": f"Low disk space — {disk_check['detail']}", "href": "/admin/health"})
    if missing_config:
        alerts.append({"level": "caution", "text": f"{len(missing_config)} config value(s) missing: {', '.join(missing_config)}", "href": "/admin/health"})
    if webhook_check["ok"] is False:
        alerts.append({"level": "caution", "text": f"No Stripe webhook received in a while — last one {webhook_check['detail']}", "href": "/admin/health"})
    if flagged_referrers:
        alerts.append({"level": "caution", "text": f"{flagged_referrers} referrer(s) flagged for review (high signups, zero conversions)", "href": "/admin/referrals"})
    if banned_count:
        alerts.append({"level": "notice", "text": f"{banned_count} user(s) currently banned", "href": "/admin/dashboard?segment=banned"})
    if pending_cancellations:
        alerts.append({"level": "notice", "text": f"{pending_cancellations} subscription(s) set to cancel at period end", "href": "/admin/dashboard?segment=pending_cancellations"})
    if active_announcements:
        alerts.append({"level": "notice", "text": f"{active_announcements} announcement(s) currently live in-app", "href": "/admin/announcements"})
    # New signups aren't a problem to flag — shown as a persistent stat line instead (below),
    # so a busy signup week doesn't crowd out the "anything actually wrong?" alerts strip.

    nav_items = [
        {"title": "Growth dashboard", "href": "/admin/dashboard",
         "desc": "Signups, conversion, active subs, MRR proxy, activity trends — click any card to drill into the matching users.",
         "stat": f"{total_users} users"},
        {"title": "System health", "href": "/admin/health",
         "desc": "Redis, database, disk, config, last webhook, and on-demand live checks against Claude/OpenAI/Stripe.",
         "stat": "issue found" if (not redis_check["ok"] or not db_check["ok"] or disk_check["ok"] is False) else "all clear"},
        {"title": "Announcements", "href": "/admin/announcements",
         "desc": "Email and/or in-app notify one or more audience segments, or a single person.",
         "stat": f"{active_announcements} live" if active_announcements else "none live"},
        {"title": "User lookup", "href": "/admin/users",
         "desc": "Search by email or username; warn, pause/resume billing, or ban/unban an account.",
         "stat": f"{total_users} total"},
        {"title": "API usage", "href": "/admin/usage",
         "desc": "Per-user capture + audio volume over a rolling window — spot abuse or runaway usage.",
         "stat": f"{usage_today[0] + usage_today[1]} today"},
        {"title": "Referrals", "href": "/admin/referrals",
         "desc": "Recent referral activity, plus referrers flagged for high signups with zero conversions.",
         "stat": f"{flagged_referrers} flagged" if flagged_referrers else "none flagged"},
        {"title": "Partners", "href": "/partner/admin",
         "desc": "Affiliate tier status and commission balances (pending / available / lifetime) per partner.",
         "stat": None},
        {"title": "Author page", "href": "/verify-author",
         "desc": "Internal author-only page, separately Basic-Auth gated.",
         "stat": None},
    ]

    return templates.TemplateResponse(request=request, name="admin_home.html", context={
        "alerts": alerts,
        "nav_items": nav_items,
        "total_users": total_users,
        "active_subs": active_subs,
        "new_7d": new_7d,
        "app_version": APP_VERSION,
        "show_navbar": True,
    })


@app.get("/admin/usage")
def admin_usage(
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


def _user_table_entries(db: Session, users: list) -> list:
    """Standard row shape for the {email, level, sessions, signup date, referrer, partner,
    actions} table — shared by /admin/users and the dashboard drill-down below so both
    render identically and both get the same _admin_actions.html buttons."""
    referrer_ids = {u.referred_by_id for u in users if u.referred_by_id}
    referrers = {u.id: u.email for u in db.query(User).filter(User.id.in_(referrer_ids)).all()} if referrer_ids else {}
    return [{
        "id": u.id,
        "email": u.email,
        "username": u.username,
        "account_level": u.account_level.value,
        "is_active": u.is_active,
        "has_sub": bool(u.stripe_sub_id),
        "is_paused": u.account_flag == "paused",
        "is_cancelling": u.sub_cancel_at is not None,
        "sessions_remaining": u.sessions_remaining,
        "created_at": u.created_at.strftime("%d %b %Y"),
        "referred_by": referrers.get(u.referred_by_id),
        "partner_status": u.partner_status,
    } for u in users]


@app.get("/admin/users")
def admin_users(
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

    return templates.TemplateResponse(request=request, name="admin_users.html", context={
        "entries": _user_table_entries(db, users),
        "q": q,
        "show_navbar": True,
        "admin_msg": request.query_params.get("admin_msg"),
    })


# Referrers with several signups but zero paid conversions — worth a manual look for
# Sybil/reciprocal-loop farming. Threshold is a starting point, not a hard rule.
_REFERRAL_FLAG_MIN_SIGNUPS = 5


def _flagged_referrer_count(db: Session) -> int:
    """Same rule as the /admin/referrals flagged list, but just the count — cheap enough to
    surface on the admin home page without building the full list of users."""
    signup_counts = dict(db.query(Referral.referrer_id, func.count(Referral.id)).group_by(Referral.referrer_id).all())
    paid_counts = dict(
        db.query(Referral.referrer_id, func.count(Referral.id))
        .filter(Referral.status == ReferralStatus.subscribed)
        .group_by(Referral.referrer_id)
        .all()
    )
    return sum(1 for rid, signups in signup_counts.items() if signups >= _REFERRAL_FLAG_MIN_SIGNUPS and paid_counts.get(rid, 0) == 0)


@app.get("/admin/referrals")
def admin_referrals(
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


# ---------------------------------------------------------------------------
# Growth dashboard — DB-derived aggregates. Actual cash lives in Stripe; the
# "MRR proxy" here is active-subs x list price, not a reconciled billing figure.
# ---------------------------------------------------------------------------

# Clicking a stat card drills into the matching users below, via ?segment=<key>. Only cards
# that map onto a clean, specific set of users are included here — pure aggregates like MRR
# pence or captures/audio counts don't correspond to a distinct user list, so they're left
# as plain (non-clickable) cards in the template.
_DASHBOARD_SEGMENTS = {
    "total_users": "All users",
    "new_7d": "New in the last 7 days",
    "new_30d": "New in the last 30 days",
    "verified": "Email verified",
    "banned": "Banned",
    "level_free": "Account level: free",
    "level_trial": "Account level: trial",
    "level_paid": "Account level: paid (session packs)",
    "level_unlimited": "Account level: unlimited (subscribers)",
    "ever_paid": "Ever paid",
    "converted": "Converted (currently paid or unlimited)",
    "active_subs": "Active subscribers",
    "pending_cancellations": "Pending cancellations",
}


def _dashboard_segment_filter(key: str):
    now = datetime.utcnow()
    if key == "total_users":
        return true()
    if key == "new_7d":
        return User.created_at >= now - timedelta(days=7)
    if key == "new_30d":
        return User.created_at >= now - timedelta(days=30)
    if key == "verified":
        return User.email_verified == True  # noqa: E712
    if key == "banned":
        return User.is_active == False  # noqa: E712
    if key == "level_free":
        return User.account_level == AccountLevel.free
    if key == "level_trial":
        return User.account_level == AccountLevel.trial
    if key == "level_paid":
        return User.account_level == AccountLevel.paid
    if key == "level_unlimited":
        return User.account_level == AccountLevel.unlimited
    if key == "ever_paid":
        return or_(User.intro_redeemed == True, User.sub_invoice_paid == True)  # noqa: E712
    if key == "converted":
        return User.account_level.in_([AccountLevel.paid, AccountLevel.unlimited])
    if key == "active_subs":
        return and_(User.account_level == AccountLevel.unlimited, User.stripe_sub_id.isnot(None))
    if key == "pending_cancellations":
        return User.sub_cancel_at.isnot(None)
    return false()


_DASHBOARD_DRILLDOWN_LIMIT = 200


@app.get("/admin/dashboard")
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    segment: str = "",
    q: str = "",
):
    now = datetime.utcnow()
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    total_users = db.query(User).count()
    new_7d = db.query(User).filter(User.created_at >= since_7d).count()
    new_30d = db.query(User).filter(User.created_at >= since_30d).count()
    verified_count = db.query(User).filter(User.email_verified == True).count()  # noqa: E712
    banned_count = db.query(User).filter(User.is_active == False).count()  # noqa: E712

    level_counts = dict(db.query(User.account_level, func.count(User.id)).group_by(User.account_level).all())
    account_mix = {level.value: level_counts.get(level, 0) for level in AccountLevel}

    ever_paid = db.query(User).filter(
        or_(User.intro_redeemed == True, User.sub_invoice_paid == True)  # noqa: E712
    ).count()

    # "Exited trial" = not currently mid-trial — the closest proxy available for a conversion
    # rate, since account_level mutates in place rather than keeping trial-cohort history.
    exited_trial = db.query(User).filter(User.account_level != AccountLevel.trial).count()
    converted = account_mix.get("paid", 0) + account_mix.get("unlimited", 0)

    active_subs = db.query(User).filter(
        User.account_level == AccountLevel.unlimited, User.stripe_sub_id.isnot(None)
    ).count()
    pending_cancellations = db.query(User).filter(User.sub_cancel_at.isnot(None)).count()

    sessions_7d = db.query(InterviewSession).filter(InterviewSession.started_at >= since_7d).count()
    sessions_30d = db.query(InterviewSession).filter(InterviewSession.started_at >= since_30d).count()
    usage_7d = db.query(
        func.coalesce(func.sum(UsageDaily.capture_count), 0), func.coalesce(func.sum(UsageDaily.audio_count), 0)
    ).filter(UsageDaily.date >= since_7d.date()).first()
    usage_30d = db.query(
        func.coalesce(func.sum(UsageDaily.capture_count), 0), func.coalesce(func.sum(UsageDaily.audio_count), 0)
    ).filter(UsageDaily.date >= since_30d.date()).first()

    total_referrals = db.query(Referral).count()
    subscribed_referrals = db.query(Referral).filter(Referral.status == ReferralStatus.subscribed).count()
    outstanding_referral_credit = db.query(func.coalesce(func.sum(User.referral_credit_pence), 0)).scalar()
    outstanding_commission = db.query(func.coalesce(func.sum(PartnerCommission.amount_pence), 0)).filter(
        PartnerCommission.status.notin_([CommissionStatus.paid, CommissionStatus.reversed])
    ).scalar()

    # SQLite's date() returns 'YYYY-MM-DD' text, which lines up with date.isoformat() below.
    signup_trend = dict(
        db.query(func.date(User.created_at), func.count(User.id))
        .filter(User.created_at >= since_30d).group_by(func.date(User.created_at)).all()
    )
    session_trend = dict(
        db.query(func.date(InterviewSession.started_at), func.count(InterviewSession.id))
        .filter(InterviewSession.started_at >= since_30d).group_by(func.date(InterviewSession.started_at)).all()
    )
    days = [since_30d.date() + timedelta(days=i) for i in range(31)]
    signup_series = [{"label": d.strftime("%d %b"), "count": signup_trend.get(d.isoformat(), 0)} for d in days]
    session_series = [{"label": d.strftime("%d %b"), "count": session_trend.get(d.isoformat(), 0)} for d in days]

    drilldown = None
    if segment in _DASHBOARD_SEGMENTS:
        drill_query = db.query(User).filter(_dashboard_segment_filter(segment))
        if q:
            like = f"%{q}%"
            drill_query = drill_query.filter(or_(User.email.ilike(like), User.username.ilike(like)))
        drill_users = drill_query.order_by(User.created_at.desc()).limit(_DASHBOARD_DRILLDOWN_LIMIT + 1).all()
        drilldown = {
            "key": segment,
            "label": _DASHBOARD_SEGMENTS[segment],
            "q": q,
            "entries": _user_table_entries(db, drill_users[:_DASHBOARD_DRILLDOWN_LIMIT]),
            "truncated": len(drill_users) > _DASHBOARD_DRILLDOWN_LIMIT,
        }

    return templates.TemplateResponse(request=request, name="admin_dashboard.html", context={
        "total_users": total_users,
        "new_7d": new_7d,
        "new_30d": new_30d,
        "verified_rate": round(verified_count / total_users * 100, 1) if total_users else 0,
        "banned_count": banned_count,
        "account_mix": account_mix,
        "ever_paid_rate": round(ever_paid / total_users * 100, 1) if total_users else 0,
        "trial_conversion_rate": round(converted / exited_trial * 100, 1) if exited_trial else 0,
        "active_subs": active_subs,
        "pending_cancellations": pending_cancellations,
        "mrr_pence": active_subs * STRIPE_SUB_PRICE_PENCE,
        "sessions_7d": sessions_7d,
        "sessions_30d": sessions_30d,
        "captures_7d": usage_7d[0], "audio_7d": usage_7d[1],
        "captures_30d": usage_30d[0], "audio_30d": usage_30d[1],
        "total_referrals": total_referrals,
        "subscribed_referrals": subscribed_referrals,
        "outstanding_referral_credit_pence": outstanding_referral_credit,
        "outstanding_commission_pence": outstanding_commission,
        "signup_series": signup_series,
        "session_series": session_series,
        "dashboard_segments": _DASHBOARD_SEGMENTS,
        "drilldown": drilldown,
        "show_navbar": True,
    })


# ---------------------------------------------------------------------------
# System health — cheap local checks always shown; deep checks (real AI/Stripe/route
# calls) are opt-in via ?deep=1 since they cost latency, tokens, and API quota.
# A separate, unauthenticated /healthz exists below the SSE section for external monitors.
# ---------------------------------------------------------------------------

async def _check_redis(r) -> dict:
    start = time.monotonic()
    try:
        await r.ping()
        return {"ok": True, "detail": "reachable", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "detail": str(e), "latency_ms": None}


def _check_database(db: Session) -> dict:
    start = time.monotonic()
    try:
        db.execute(text("SELECT 1"))
        latency = round((time.monotonic() - start) * 1000, 1)
        user_count = db.query(User).count()
        db_filename = "test_users.db" if os.getenv("TESTING") == "1" else "users.db"
        db_path = os.path.join(DATA_DIR, db_filename)
        size_mb = round(os.path.getsize(db_path) / 1024 / 1024, 2) if os.path.exists(db_path) else 0
        return {"ok": True, "detail": f"{user_count} users, {size_mb} MB", "latency_ms": latency}
    except Exception as e:
        return {"ok": False, "detail": str(e), "latency_ms": None}


def _check_disk() -> dict:
    try:
        usage = shutil.disk_usage(DATA_DIR)
        free_gb = round(usage.free / 1024 ** 3, 1)
        total_gb = round(usage.total / 1024 ** 3, 1)
        pct_free = round(usage.free / usage.total * 100, 1) if usage.total else 0
        return {"ok": pct_free > 10, "detail": f"{free_gb} GB free of {total_gb} GB ({pct_free}%)", "latency_ms": None}
    except Exception as e:
        return {"ok": False, "detail": str(e), "latency_ms": None}


async def _last_webhook_status(r) -> dict:
    raw = await r.get("health:last_webhook")
    if not raw:
        return {"ok": None, "detail": "No webhook received yet this run", "latency_ms": None}
    age_min = (datetime.utcnow() - datetime.fromisoformat(raw)).total_seconds() / 60
    stale = age_min > 60 * 72  # 72h with zero Stripe events would be unusual for a live paid product
    return {"ok": not stale, "detail": f"{round(age_min)} min ago", "latency_ms": None}


# ---------------------------------------------------------------------------
# Metrics section of /admin/health — cheap local reads, no outbound calls.
# Resend-failure/5xx counters are hourly buckets written by metrics.py (mailer.py) and the
# _request_logger middleware above; summed here over a rolling 24h window.
# ---------------------------------------------------------------------------

async def _incr_hourly_metric(r, prefix: str) -> None:
    """Best-effort — a metrics failure must never break the request/email it's counting."""
    try:
        key = hourly_bucket_key(prefix)
        await r.incr(key)
        await r.expire(key, METRIC_TTL_SECONDS)
    except Exception:
        pass


async def _sum_hourly_metric(r, prefix: str, hours: int = 24) -> int:
    now = datetime.utcnow()
    keys = [hourly_bucket_key(prefix, now - timedelta(hours=i)) for i in range(hours)]
    try:
        values = await r.mget(keys)
    except Exception:
        return 0
    return sum(int(v) for v in values if v)


_LOG_FILENAME = "test_app.log" if os.getenv("TESTING") == "1" else "app.log"
_LOG_ENTRY_HEADER_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[(\w+)\]")


def _recent_error_log_entries(max_entries: int = 20) -> list:
    """Tails app.log (written by the RotatingFileHandler set up in analytics.py) for the
    admin health page's 'Recent errors' section. Groups continuation lines (tracebacks)
    with the header line that started them — filtering line-by-line would strip a
    traceback's body away from the ERROR line that explains what failed."""
    log_path = os.path.join(DATA_DIR, _LOG_FILENAME)
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return []

    entries, current, current_level = [], [], None
    for line in lines:
        m = _LOG_ENTRY_HEADER_RE.match(line)
        if m:
            if current and current_level in ("ERROR", "CRITICAL"):
                entries.append("".join(current).rstrip())
            current, current_level = [line], m.group(1)
        else:
            current.append(line)
    if current and current_level in ("ERROR", "CRITICAL"):
        entries.append("".join(current).rstrip())
    return entries[-max_entries:]


def _db_disk_usage() -> dict:
    """DB file size already appears folded into the Database core check (row count + size);
    this is the same number surfaced on its own, plus the WAL/SHM sidecars for true on-disk
    footprint — those aren't reflected by the main file's size alone under WAL mode."""
    db_filename = "test_users.db" if os.getenv("TESTING") == "1" else "users.db"
    total_bytes = 0
    for suffix in ("", "-wal", "-shm"):
        path = os.path.join(DATA_DIR, db_filename + suffix)
        if os.path.exists(path):
            total_bytes += os.path.getsize(path)
    size_mb = round(total_bytes / 1024 / 1024, 2)
    return {"ok": True, "detail": f"{size_mb} MB on disk (main + WAL/SHM)", "latency_ms": None}


def _billing_summary(db: Session) -> dict:
    active_subs = db.query(User).filter(
        User.account_level == AccountLevel.unlimited, User.stripe_sub_id.isnot(None)
    ).count()
    pending_cancellations = db.query(User).filter(User.sub_cancel_at.isnot(None)).count()
    paid_session_users = db.query(User).filter(User.account_level == AccountLevel.paid).count()
    low_sessions = db.query(User).filter(
        User.account_level == AccountLevel.paid, User.sessions_remaining <= 1
    ).count()
    detail = (
        f"{active_subs} active sub(s), {paid_session_users} session user(s) "
        f"({low_sessions} on ≤1 session), {pending_cancellations} cancelling"
    )
    return {"ok": True, "detail": detail, "latency_ms": None}


_RATE_LIMIT_ENDPOINTS = {
    # endpoint name (matches the `endpoint` arg passed to _rate_limit) -> its per-minute `limit`.
    "login_ip": 20, "login_user": 6, "register": 10,
    "resend_verification": 3, "forgot_password_email": 3, "forgot_password_ip": 10,
    "capture": 6, "audio": 10,
}


async def _rate_limit_headroom(r) -> list:
    """Per-minute rate-limit activity across the endpoints _rate_limit gates. Scans the
    `rl:*:{endpoint}:count` keys (the per-minute counters) rather than every individual
    user/IP, and reports the busiest single counter seen against its configured limit —
    enough to see at a glance whether anyone is close to the ceiling, without walking
    every key's owner."""
    results = []
    for endpoint, limit in _RATE_LIMIT_ENDPOINTS.items():
        try:
            keys = [k async for k in r.scan_iter(match=f"rl:*:{endpoint}:count", count=200)]
            values = await r.mget(keys) if keys else []
        except Exception as e:
            results.append({"name": endpoint, "ok": None, "detail": f"scan failed: {e}", "latency_ms": None})
            continue
        counts = [int(v) for v in values if v]
        peak = max(counts) if counts else 0
        results.append({
            "name": endpoint,
            "ok": peak < limit,
            "detail": f"{len(counts)} active, peak {peak}/{limit} per min",
            "latency_ms": None,
        })
    return results


_CONFIG_CHECKS = [
    ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
    ("OPENAI_API_KEY", OPENAI_API_KEY),
    ("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY),
    ("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET),
    ("STRIPE_SUB_PRICE_ID", STRIPE_SUB_PRICE_ID),
    ("STRIPE_SESSIONS_PRICE_ID", STRIPE_SESSIONS_PRICE_ID),
    ("STRIPE_SESSIONS_PACK_PRICE_ID", STRIPE_SESSIONS_PACK_PRICE_ID),
    ("RESEND_API_KEY", RESEND_API_KEY),
    ("AUTHOR_PASSWORD", AUTHOR_PASSWORD),
    ("DEEPGRAM_API_KEY", DEEPGRAM_API_KEY),
]


def _config_status() -> list:
    return [{"name": name, "configured": bool(val)} for name, val in _CONFIG_CHECKS]


def _format_duration(seconds: int) -> str:
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = [f"{days}d"] if days else []
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _check_anthropic() -> dict:
    start = time.monotonic()
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=8,
            messages=[{"role": "user", "content": "Reply with only: ok"}],
        )
        ok = resp.content[0].text.strip().lower().startswith("ok")
        return {"ok": ok, "detail": "responded" if ok else "unexpected response", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "detail": str(e), "latency_ms": round((time.monotonic() - start) * 1000, 1)}


def _check_openai() -> dict:
    start = time.monotonic()
    try:
        # Retrieve the one model this app actually calls (transcription), not
        # models.list() — that endpoint returns OpenAI's entire ~125-model catalog and
        # measured 5x+ slower here for no extra signal about whether audio capture works.
        OpenAI(api_key=OPENAI_API_KEY).models.retrieve("gpt-4o-transcribe")
        return {"ok": True, "detail": "reachable", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "detail": str(e), "latency_ms": round((time.monotonic() - start) * 1000, 1)}


def _check_deepgram() -> dict:
    start = time.monotonic()
    if not DEEPGRAM_API_KEY:
        return {"ok": False, "detail": "not configured — Whisper failures won't have a fallback", "latency_ms": 0}
    try:
        resp = requests.get(
            "https://api.deepgram.com/v1/projects",
            headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        return {"ok": True, "detail": "reachable", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "detail": str(e), "latency_ms": round((time.monotonic() - start) * 1000, 1)}


def _check_stripe() -> dict:
    start = time.monotonic()
    try:
        stripe.Balance.retrieve()
        return {"ok": True, "detail": "reachable", "latency_ms": round((time.monotonic() - start) * 1000, 1)}
    except Exception as e:
        return {"ok": False, "detail": str(e), "latency_ms": round((time.monotonic() - start) * 1000, 1)}


def _check_sideload() -> dict:
    """Checks both the jsDelivr CDN fronting the extension zip and the same-origin mirror
    /install-manual falls back to — see SIDELOAD_ZIP_URL's comment in config.py."""
    start = time.monotonic()
    if not SIDELOAD_ENABLED:
        return {"ok": None, "detail": "sideload page disabled (SIDELOAD_ENABLED=0)", "latency_ms": None}
    try:
        cdn = requests.head(SIDELOAD_ZIP_URL, timeout=8, allow_redirects=True)
        mirror = requests.head(f"{BASE_URL}/static/extension/interviewace-extension.zip", timeout=8, allow_redirects=True)
        ok = cdn.status_code < 400 and mirror.status_code < 400
        return {
            "ok": ok,
            "detail": f"CDN HTTP {cdn.status_code}, mirror HTTP {mirror.status_code}",
            "latency_ms": round((time.monotonic() - start) * 1000, 1),
        }
    except Exception as e:
        return {"ok": False, "detail": str(e), "latency_ms": round((time.monotonic() - start) * 1000, 1)}


_HEALTH_CHECK_ROUTES = ["/", "/login", "/pricing", "/faq", "/healthz"]


def _check_routes() -> list:
    results = []
    for path in _HEALTH_CHECK_ROUTES:
        start = time.monotonic()
        try:
            resp = requests.get(f"{BASE_URL}{path}", timeout=5)
            results.append({
                "name": path, "ok": resp.status_code < 400,
                "detail": f"HTTP {resp.status_code}", "latency_ms": round((time.monotonic() - start) * 1000, 1),
            })
        except Exception as e:
            results.append({"name": path, "ok": False, "detail": str(e), "latency_ms": round((time.monotonic() - start) * 1000, 1)})
    return results


@app.get("/admin/health")
async def admin_health(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
):
    r = request.app.state.redis
    checks = {
        "redis": await _check_redis(r),
        "database": _check_database(db),
        "disk": _check_disk(),
        "last_webhook": await _last_webhook_status(r),
    }
    resend_failures_24h = await _sum_hourly_metric(r, EMAIL_FAIL_PREFIX)
    http_5xx_24h = await _sum_hourly_metric(r, HTTP_5XX_PREFIX)
    metrics = {
        "db_disk": _db_disk_usage(),
        "billing": _billing_summary(db),
        "resend_failures": {"ok": resend_failures_24h == 0, "detail": f"{resend_failures_24h} in last 24h", "latency_ms": None},
        "http_5xx": {"ok": http_5xx_24h == 0, "detail": f"{http_5xx_24h} in last 24h", "latency_ms": None},
        "rate_limits": await _rate_limit_headroom(r),
    }
    uptime_seconds = int((datetime.utcnow() - request.app.state.started_at).total_seconds())
    return templates.TemplateResponse(request=request, name="admin_health.html", context={
        "checks": checks,
        "metrics": metrics,
        "config_status": _config_status(),
        "app_version": APP_VERSION,
        "uptime_display": _format_duration(uptime_seconds),
        "show_navbar": True,
    })


@app.get("/admin/health/logs")
def admin_health_logs(
    max_entries: int = 20,
    _: None = Depends(_require_author),
):
    """On-demand — the page fetches this only when the 'Show recent errors' button under
    the Error rate row is clicked, rather than reading/parsing the log file on every plain
    page load (mirrors why the deep checks below are opt-in, not cost-driven here but the
    same 'skip it until someone actually wants it' logic)."""
    return {
        "entries": list(reversed(_recent_error_log_entries(max_entries))),
        "log_file_path": os.path.join(DATA_DIR, _LOG_FILENAME),
    }


@app.get("/admin/health/deep/{name}")
async def admin_health_deep_check(
    name: str,
    _: None = Depends(_require_author),
):
    """One deep check per request — the page fires these in parallel and fills in each row
    as its own fetch resolves, rather than waiting for the slowest check to render anything.
    Dispatches by name (rather than a name->function dict built at import time) so tests can
    still `patch("server._check_anthropic", ...)` and have it take effect here."""
    if name == "routes":
        return {"routes": await asyncio.to_thread(_check_routes)}
    if name == "anthropic":
        return await asyncio.to_thread(_check_anthropic)
    if name == "openai":
        return await asyncio.to_thread(_check_openai)
    if name == "deepgram":
        return await asyncio.to_thread(_check_deepgram)
    if name == "stripe":
        return await asyncio.to_thread(_check_stripe)
    if name == "sideload":
        return await asyncio.to_thread(_check_sideload)
    raise HTTPException(status_code=404, detail="Unknown check")


@app.get("/healthz")
async def healthz(request: Request, db: Session = Depends(get_db)):
    """Public, unauthenticated liveness check — no secrets, no user data. Point an external
    monitor (UptimeRobot, healthchecks.io, ...) at this so you get paged even when the app
    is down entirely, which /admin/health can't do since it needs the app up to view it."""
    r = request.app.state.redis
    redis_ok = (await _check_redis(r))["ok"]
    db_ok = _check_database(db)["ok"]
    ok = bool(redis_ok and db_ok)
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ok" if ok else "degraded", "redis": redis_ok, "database": db_ok},
    )


def _admin_redirect(return_to: str, msg: str) -> RedirectResponse:
    if not return_to.startswith("/admin/"):
        return_to = "/admin/usage"
    sep = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{sep}{urlencode({'admin_msg': msg})}", status_code=303)


@app.post("/admin/users/{user_id}/ban")
def admin_ban_user(
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
def admin_unban_user(
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
def admin_pause_subscription(
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
def admin_resume_subscription(
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
def admin_warn_user(
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


@app.post("/admin/users/{user_id}/send-expiry-reminder")
def admin_send_expiry_reminder(
    user_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    return_to: str = Form(default="/admin/usage"),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if not target.sub_cancel_at:
        return _admin_redirect(return_to, f"{target.email} has no scheduled cancellation")
    cancel_date = target.sub_cancel_at.strftime("%d %b %Y")
    send_expiry_reminder_email(target.email, cancel_date)
    track(target.id, "admin_expiry_reminder_sent")
    logger.info("[admin] expiry reminder sent to user=%s", target.email)
    return _admin_redirect(return_to, f"Expiry reminder emailed to {target.email}")


@app.post("/admin/users/{user_id}/send-low-sessions")
def admin_send_low_sessions(
    user_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    return_to: str = Form(default="/admin/usage"),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    send_low_sessions_email(target.email, target.sessions_remaining)
    track(target.id, "admin_low_sessions_sent")
    logger.info("[admin] low-sessions notice sent to user=%s (%d left)", target.email, target.sessions_remaining)
    return _admin_redirect(return_to, f"Low-sessions notice emailed to {target.email}")


# ---------------------------------------------------------------------------
# Announcements — email and/or in-app, targeted at a segment or one person.
# In-app delivery is DB-backed (like account_flag above), not SSE: /stream is
# per-user, paid-only, and only live on /app, so it can't reliably broadcast.
# ---------------------------------------------------------------------------

_SEGMENTS = [
    ("everyone", "Everyone"),
    ("trial", "Trial (active)"),
    ("sessions", "Session-pack buyers"),
    ("subscribers", "Subscribers"),
    ("subscribers_cancelling", "Subscribers — cancelling"),
    ("lapsed_trial", "Lapsed — used trial, never paid"),
    ("lapsed_paid", "Lapsed — previously paid"),
    ("free_inactive", "Free — never started a trial"),
    ("never_paid", "Never paid (trial + free)"),
    ("individual", "Individual (single email)"),
]
_SEGMENT_KEYS = {key for key, _label in _SEGMENTS}


def _segment_filter(db: Session, segment: str, target_email: Optional[str] = None):
    """Single definition of who's "in" a segment, as a filter condition rather than a full
    query — lets _segment_query OR several of these together for multi-segment targeting."""
    has_session = db.query(InterviewSession.id).filter(InterviewSession.user_id == User.id).exists()

    if segment == "everyone":
        return User.is_active == True  # noqa: E712
    if segment == "trial":
        return User.account_level == AccountLevel.trial
    if segment == "sessions":
        return User.account_level == AccountLevel.paid
    if segment == "subscribers":
        return User.account_level == AccountLevel.unlimited
    if segment == "subscribers_cancelling":
        return and_(User.account_level == AccountLevel.unlimited, User.sub_cancel_at.isnot(None))
    if segment == "lapsed_trial":
        return and_(
            User.account_level == AccountLevel.free,
            User.intro_redeemed == False, User.sub_invoice_paid == False,  # noqa: E712
            has_session,
        )
    if segment == "lapsed_paid":
        return and_(
            User.account_level == AccountLevel.free,
            or_(User.intro_redeemed == True, User.sub_invoice_paid == True),  # noqa: E712
        )
    if segment == "free_inactive":
        return and_(
            User.account_level == AccountLevel.free,
            User.intro_redeemed == False, User.sub_invoice_paid == False,  # noqa: E712
            ~has_session,
        )
    if segment == "never_paid":
        return and_(
            User.account_level.in_([AccountLevel.trial, AccountLevel.free]),
            User.intro_redeemed == False, User.sub_invoice_paid == False,  # noqa: E712
        )
    if segment == "individual":
        return (User.email == target_email) if target_email else false()
    return false()


def _segment_query(db: Session, segment: str, target_email: Optional[str] = None):
    """`segment` is a single key, or several comma-joined keys for multi-audience targeting
    (e.g. "trial,sessions") — matched users are the union (OR), so someone in more than one
    selected segment is still only counted/emailed once."""
    keys = [k for k in segment.split(",") if k]
    conditions = [_segment_filter(db, k, target_email) for k in keys] or [false()]
    return db.query(User).filter(User.is_active == True).filter(or_(*conditions))  # noqa: E712


def _user_in_segment(db: Session, user: User, segment: str, target_email: Optional[str] = None) -> bool:
    return _segment_query(db, segment, target_email).filter(User.id == user.id).first() is not None


def _email_recipients(db: Session, segment: str, target_email: Optional[str] = None) -> list:
    # Verified-only — avoids bouncing mail at addresses nobody's confirmed ownership of.
    return _segment_query(db, segment, target_email).filter(User.email_verified == True).all()  # noqa: E712


def _send_announcement_emails(announcement_id: int, subject: str, body: str, segment: str, target_email: Optional[str]) -> None:
    """Runs in a threadpool via BackgroundTasks (see create_announcement) — opens its own
    session since the request's db dependency closes as soon as the response is sent."""
    db = SessionLocal()
    try:
        recipients = _email_recipients(db, segment, target_email)
        for u in recipients:
            send_announcement_email(u.email, subject, body)
            time.sleep(0.1)  # light throttle — respect Resend's per-second send cap
        ann = db.query(Announcement).filter(Announcement.id == announcement_id).first()
        if ann:
            ann.email_recipient_count = len(recipients)
            db.commit()
        logger.info("[announcement] id=%s emailed %d recipients (segment=%s)", announcement_id, len(recipients), segment)
    finally:
        db.close()


@app.get("/admin/announcements")
def admin_announcements(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
):
    counts = {key: _segment_query(db, key).count() for key, _label in _SEGMENTS if key != "individual"}
    history = db.query(Announcement).order_by(Announcement.created_at.desc()).limit(30).all()
    return templates.TemplateResponse(request=request, name="admin_announcements.html", context={
        "segments": _SEGMENTS,
        "counts": counts,
        "history": history,
        "show_navbar": True,
        "admin_msg": request.query_params.get("admin_msg"),
    })


@app.get("/admin/announcements/count")
def announcement_segment_count(
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    segment: list[str] = Query(default=[]),
    target_email: str = Query(default=""),
):
    """Live recipient count for the compose form — exact, not summed, since _segment_query
    ORs the selected segments together and a single query naturally dedupes anyone who
    matches more than one."""
    keys = [s for s in segment if s in _SEGMENT_KEYS]
    if not keys:
        return {"count": 0}
    count = _segment_query(db, ",".join(keys), target_email.strip() or None).count()
    return {"count": count}


@app.post("/admin/announcements")
def create_announcement(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
    subject: str = Form(...),
    body: str = Form(...),
    channel: str = Form(...),
    segment: list[str] = Form(...),
    target_email: str = Form(default=""),
):
    keys = sorted(set(segment))
    if not keys or any(k not in _SEGMENT_KEYS for k in keys) or channel not in ("email", "in_app", "both"):
        raise HTTPException(status_code=400, detail="Invalid segment or channel")
    target_email = target_email.strip() or None
    if "individual" in keys and not target_email:
        return _admin_redirect("/admin/announcements", "Individual segment needs a target email")

    segment_str = ",".join(keys)
    ann = Announcement(
        subject=subject.strip(),
        body=body.strip(),
        channel=channel,
        segment=segment_str,
        target_email=target_email,
        in_app_active=channel in ("in_app", "both"),
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)

    if channel in ("email", "both"):
        background_tasks.add_task(_send_announcement_emails, ann.id, ann.subject, ann.body, segment_str, target_email)

    logger.warning("[admin] announcement created id=%s segment=%s channel=%s", ann.id, segment_str, channel)
    return _admin_redirect("/admin/announcements", f"Announcement #{ann.id} created ({channel} → {segment_str})")


@app.post("/admin/announcements/{announcement_id}/deactivate")
def deactivate_announcement(
    announcement_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(_require_author),
):
    ann = db.query(Announcement).filter(Announcement.id == announcement_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="Announcement not found")
    ann.in_app_active = False
    db.commit()
    return _admin_redirect("/admin/announcements", f"Announcement #{ann.id} deactivated")


@app.post("/announcements/{announcement_id}/dismiss")
def dismiss_announcement(
    announcement_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    already = db.query(AnnouncementDismissal).filter(
        AnnouncementDismissal.announcement_id == announcement_id,
        AnnouncementDismissal.user_id == user.id,
    ).first()
    if not already:
        db.add(AnnouncementDismissal(announcement_id=announcement_id, user_id=user.id))
        db.commit()
    return Response(status_code=204)


@app.get("/settings")
async def settings_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    ref_success: Optional[str] = None,
    ref_error: Optional[str] = None,
    offer: Optional[str] = None,
):
    r = request.app.state.redis
    complexity = await get_complexity(r, user.id)

    def _load_page_data():
        _ensure_api_token(user, db)
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
        return account_flag_notice, cancel_at, hk, contexts

    account_flag_notice, cancel_at, hk, contexts = await run_in_threadpool(_load_page_data)

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
        "complexity": complexity,
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
def get_screenshot(user: User = Depends(require_subscription)):
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
def setup_complete(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    user = await run_in_threadpool(lambda: db.query(User).filter(User.id == int(user_id_str)).first())
    if not user:
        return RedirectResponse("/login?error=link_expired", status_code=303)
    jwt_token = create_token(user.id)
    response = RedirectResponse("/app", status_code=303)
    response.set_cookie("session", jwt_token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return response


@app.post("/api/trial/start")
async def trial_start(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.account_level != AccountLevel.trial:
        raise HTTPException(status_code=400, detail="Not a trial account")

    def _start():
        existing = db.query(InterviewSession).filter(
            InterviewSession.user_id == user.id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Trial already used")
        user.setup_complete = True
        session, _ = _get_or_create_session(db, user.id, TRIAL_DURATION)
        db.commit()
        return session

    session = await run_in_threadpool(_start)
    # The check inside _start() guarantees this session was just newly created —
    # clear unconditionally so a trial never inherits history from a prior session.
    await _clear_history(request.app.state.redis, user.id)
    track(user.id, "trial_started")
    return {
        "started_at": session.started_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
        "seconds_remaining": int(TRIAL_DURATION.total_seconds()),
    }


@app.get("/api/trial/status")
def trial_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    def _account_bookkeeping():
        _record_usage(db, user.id, "capture")
        created = False
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
            _, created = _get_or_create_session(db, user.id)
        return created

    created = await run_in_threadpool(_account_bookkeeping)
    if created:
        await _clear_history(r, user.id)

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
    prompt = AI_PROMPT + _context_suffix(user, db) + COMPLEXITY_SUFFIX[complexity] + RESPONSE_STYLE_SUFFIX[style]

    history = await _load_history_messages(r, user.id)
    full_text = await _stream_ai_response(r, user.id, prompt, img_b64=img_b64, capture_id=capture_id, history=history)
    await _append_history(r, user.id, "screenshot", SCREENSHOT_PLACEHOLDER, full_text, user.account_level)

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
    def _account_bookkeeping():
        _record_usage(db, user.id, "capture")
        created = False
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
            _, created = _get_or_create_session(db, user.id)
        return created

    created = await run_in_threadpool(_account_bookkeeping)
    if created:
        await _clear_history(r, user.id)

    await broadcast(r, user.id, "typing-working", {"text": body.text})

    style      = _user_response_style(user)
    complexity = await get_complexity(r, user.id)
    prompt = AI_PROMPT + _context_suffix(user, db) + COMPLEXITY_SUFFIX[complexity] + f"\n\nTyped input: {body.text}" + RESPONSE_STYLE_SUFFIX[style]

    history = await _load_history_messages(r, user.id)
    full_text = await _stream_ai_response(r, user.id, prompt, history=history)
    await _append_history(r, user.id, "text", body.text, full_text, user.account_level)

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
        try:
            with open(tmp_path, "rb") as f:
                transcript = await asyncio.to_thread(
                    openai_client.audio.transcriptions.create,
                    model="gpt-4o-transcribe",
                    file=f,
                )
            transcription_text = transcript.text
        except Exception as transcribe_exc:
            if not DEEPGRAM_API_KEY:
                raise
            logger.error("[audio] OpenAI transcription failed, failing over to Deepgram: %s", transcribe_exc)
            transcription_text = await asyncio.to_thread(_deepgram_transcribe, audio_bytes, suffix)
        await broadcast(r, user.id, "audio-transcribed", {"transcription": transcription_text})

        style      = _user_response_style(user)
        complexity = await get_complexity(r, user.id)
        prompt = AI_PROMPT + _context_suffix(user, db) + COMPLEXITY_SUFFIX[complexity] + f"\n\nThe interviewer said: {transcription_text}" + RESPONSE_STYLE_SUFFIX[style]
        history = await _load_history_messages(r, user.id)
        full_text = await _stream_ai_response(r, user.id, prompt, history=history)
        await _append_history(r, user.id, "audio", transcription_text, full_text, user.account_level)

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
def set_style_token(data: ResponseStyleRequest, user: User = Depends(get_user_by_token), db: Session = Depends(get_db)):
    user.response_style = data.style
    db.commit()
    return {"status": "ok", "style": data.style.value}


@app.post("/api/settings/hotkeys")
def save_hotkeys(data: HotkeySettings, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
def save_passthrough(data: PassthroughSetting, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.typing_passthrough = data.enabled
    db.commit()
    return {"status": "ok"}


@app.post("/api/settings/replay")
def save_replay(data: ReplaySettings, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.replay_enabled = data.enabled
    user.replay_seconds = data.seconds
    db.commit()
    return {"status": "ok"}


@app.post("/api/settings/response-style")
def save_response_style(data: ResponseStyleRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.response_style = data.style
    db.commit()
    return {"status": "ok", "style": data.style.value}


@app.post("/api/settings/context")
def save_context(data: ContextSaveRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
def activate_context(data: ContextActivateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
def regenerate_api_token(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
def update_account(
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
def change_password(
    body: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    password_error = validate_password(body.new_password)
    if password_error:
        raise HTTPException(status_code=400, detail=password_error)
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"status": "ok"}


@app.get("/account/delete")
def account_delete_page(request: Request, user: User = Depends(get_current_user)):
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
    def _delete():
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
        return user_id

    user_id = await run_in_threadpool(_delete)

    r = request.app.state.redis
    await r.delete(_capture_key(user_id), _complexity_key(user_id), _history_key(user_id))

    response = RedirectResponse("/login?deleted=1", status_code=303)
    response.delete_cookie("session")
    return response


# ---------------------------------------------------------------------------
# Billing routes
# ---------------------------------------------------------------------------

@app.get("/billing/checkout")
def billing_checkout(user: User = Depends(get_current_user), db: Session = Depends(get_db), plan: str = "subscription"):
    apply_discount = False
    if plan == "subscription" and user.referred_by_id:
        ref = db.query(Referral).filter(Referral.referee_id == user.id).first()
        if ref and ref.status != ReferralStatus.subscribed:
            apply_discount = True
    url = create_checkout_session(user, db, plan=plan, apply_referral_discount=apply_discount)
    track(user.id, "checkout_initiated", plan=plan)
    return RedirectResponse(url)


@app.get("/billing/cancel")
def billing_cancel(request: Request, user: User = Depends(get_current_user)):
    hk = _user_hotkeys(user)
    return templates.TemplateResponse(request=request, name="cancel_confirm.html", context={
        "hotkey_capture": hk["capture"],
        "hotkey_toggle":  hk["toggle"],
        "offer_eligible": user.sub_invoice_paid and not user.retention_offer_claimed,
    })


@app.post("/billing/offer")
def billing_offer(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        apply_retention_coupon(user)
        user.retention_offer_claimed = True
        db.commit()
    except Exception as e:
        logger.error("[retention] failed to apply coupon for %s: %s", user.email, e)
    return RedirectResponse("/settings?offer=claimed", status_code=303)


@app.post("/billing/cancel/confirm")
def billing_cancel_confirm(
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
def billing_portal(user: User = Depends(get_current_user)):
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found.")
    url = create_portal_session(user)
    return RedirectResponse(url, status_code=303)


@app.post("/billing/feedback")
def billing_feedback(
    user: User = Depends(get_current_user),
    reason: str = Form(default=""),
    detail: str = Form(default=""),
):
    if reason:
        send_cancel_feedback_email(user.email, reason, detail, kept=True)
    return RedirectResponse("/settings", status_code=303)


@app.get("/billing/success")
def billing_success(request: Request, user: User = Depends(get_optional_user), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse("/login?next=/billing/success", status_code=302)
    db.refresh(user)
    return templates.TemplateResponse(request=request, name="billing_success.html", context={})


@app.get("/api/billing/status")
def billing_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    # Health page staleness check (see /admin/health) — best-effort, never blocks the webhook ack.
    try:
        await request.app.state.redis.set("health:last_webhook", datetime.utcnow().isoformat())
    except Exception:
        pass
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
        # Runtime writes under the repo (captured screenshots, the SQLite journal, __pycache__)
        # otherwise register as "source changed" to the reloader and trigger a restart on every
        # capture — killing in-flight SSE streams mid-interview. Exclude everything that isn't
        # actually source.
        uvicorn.run(
            "server:app", host=SERVER_HOST, port=SERVER_PORT, reload=True,
            reload_excludes=["screenshots/*", "*.db", "*.db-*", "__pycache__/*", "*.pyc"],
        )
    else:
        uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
