import asyncio
import base64
import json
import os
import secrets
import tempfile
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import anthropic
import redis.asyncio as aioredis
import uvicorn
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import OpenAI
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import create_token, generate_unique_referral_code, get_current_user, get_optional_user, get_user_by_token, hash_password, verify_password
from billing import cancel_subscription, create_checkout_session, create_portal_session, handle_webhook_event
from config import AI_PROMPT, ANTHROPIC_API_KEY, AUTHOR_PASSWORD, BASE_URL, OPENAI_API_KEY, REDIS_URL, SERVER_HOST, SERVER_PORT
from mailer import send_cancel_feedback_email, send_verification_email
from database import get_db, init_db
from models import AccountLevel, InterviewSession, Referral, ReferralStatus, User

templates = Jinja2Templates(directory="templates")
SCREENSHOTS_DIR = Path("screenshots")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    if os.getenv("TESTING") == "1":
        import fakeredis.aioredis
        app.state.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    else:
        app.state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        await app.state.redis.ping()
    print(f"[ready] http://localhost:{SERVER_PORT}")
    try:
        yield
    finally:
        await app.state.redis.aclose()


app = FastAPI(lifespan=lifespan)
app.mount("/css", StaticFiles(directory="css"), name="css")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
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


HOTKEY_DEFAULTS = {"capture": "Ctrl+Shift+7", "audio": "Ctrl+Shift+8", "toggle": "Ctrl+Shift+9"}


def _user_hotkeys(user) -> dict:
    return {
        "capture": user.hotkey_capture or HOTKEY_DEFAULTS["capture"],
        "audio":   user.hotkey_audio   or HOTKEY_DEFAULTS["audio"],
        "toggle":  user.hotkey_toggle  or HOTKEY_DEFAULTS["toggle"],
    }


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
                      limit_msg: str = "Rate limit exceeded — try again in a minute"):
    last_key  = f"rl:{user_id}:{endpoint}:last"
    count_key = f"rl:{user_id}:{endpoint}:count"
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
    await r.set(last_key, time.time(), ex=cooldown + 5)


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
            await broadcast(r, user.id, "trial_expired", {})
            raise HTTPException(status_code=403, detail="trial_expired")


def _ensure_api_token(user: User, db: Session):
    if not user.api_token:
        user.api_token = secrets.token_urlsafe(32)
        db.commit()


_REFERRAL_ERROR_MESSAGES = {
    "invalid_code":    "That code doesn't look right — double-check and try again.",
    "already_referred": "You've already applied a referral code.",
    "self_referral":   "You can't use your own referral code.",
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


class CaptureRequest(BaseModel):
    image: str        # base64 PNG, optionally prefixed with "data:image/png;base64,"
    complexity: int = Field(default=2, ge=1, le=3)
    monitor: str = "browser"


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/login")
async def login_page(request: Request, user: Optional[User] = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/app")
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.post("/auth/login")
async def auth_login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled.")

    user.last_login = datetime.utcnow()
    db.commit()

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

    verify_token = secrets.token_urlsafe(32)
    user.verify_token = verify_token
    db.commit()
    send_verification_email(user.email, verify_token)

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
    if user.account_level == AccountLevel.trial:
        return RedirectResponse("/onboarding")
    return RedirectResponse("/app")


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
    return templates.TemplateResponse(request=request, name="landing.html", context={"user": user})


@app.get("/app")
async def index(request: Request, user: User = Depends(require_user)):
    if not user.email_verified:
        return RedirectResponse("/verify-pending")
    if user.account_level == AccountLevel.free:
        return RedirectResponse("/pricing")
    if user.account_level == AccountLevel.trial and not user.setup_complete:
        return RedirectResponse("/onboarding")
    return templates.TemplateResponse(request=request, name="index.html", context=_user_hotkeys(user))


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
    hk = _user_hotkeys(user)
    return templates.TemplateResponse(request=request, name="onboarding.html", context={
        "api_token": user.api_token,
        "base_url": BASE_URL,
        "hotkey_capture": hk["capture"],
        "hotkey_audio":   hk["audio"],
        "hotkey_toggle":  hk["toggle"],
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
    return templates.TemplateResponse(request=request, name="trial_end.html", context={})


@app.get("/pricing")
async def pricing_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(request=request, name="pricing.html", context={
        "intro_redeemed": user.intro_redeemed,
        "sessions_remaining": user.sessions_remaining,
    })


_basic = HTTPBasic()

def _require_author(credentials: HTTPBasicCredentials = Depends(_basic)):
    ok = AUTHOR_PASSWORD and secrets.compare_digest(credentials.password.encode(), AUTHOR_PASSWORD.encode())
    if not ok:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": 'Basic realm="author"'})

@app.get("/verify-author")
async def author_page(request: Request, _: None = Depends(_require_author)):
    return templates.TemplateResponse(request=request, name="author.html", context={})


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
    total_pence = 0
    for ref_row, referee_user in referral_rows:
        credited = (200 if ref_row.intro_credited else 0) + (300 if ref_row.sub_credited else 0)
        total_pence += credited
        referrals.append({
            "referee_email": referee_user.email,
            "joined_date": f"{ref_row.created_at.day} {ref_row.created_at.strftime('%b %Y')}",
            "status": ref_row.status.value,
        })
    return templates.TemplateResponse(request=request, name="referral.html", context={
        "referral_code": user.referral_code,
        "referrals": referrals,
        "total_credits_earned": total_pence / 100,
        "is_referred": user.referred_by_id is not None,
        "ref_success": ref_success == "1",
        "error_msg": _REFERRAL_ERROR_MESSAGES.get(ref_error),
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
    referrer = db.query(User).filter(User.referral_code == _parse_referral_code(code)).first()
    if not referrer:
        return redirect("ref_error", "invalid_code")
    if referrer.id == user.id:
        return redirect("ref_error", "self_referral")
    user.referred_by_id = referrer.id
    db.add(Referral(referrer_id=referrer.id, referee_id=user.id))
    db.commit()
    return redirect("ref_success", "1")


@app.get("/settings")
async def settings_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    ref_success: Optional[str] = None,
    ref_error: Optional[str] = None,
):
    _ensure_api_token(user, db)
    cancel_at = user.sub_cancel_at.strftime("%d %B %Y").lstrip("0") if user.sub_cancel_at else None
    hk = _user_hotkeys(user)
    return templates.TemplateResponse(request=request, name="settings.html", context={
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "account_level": user.account_level.value,
        "sessions_remaining": user.sessions_remaining,
        "api_token": user.api_token,
        "base_url": BASE_URL,
        "sub_cancel_at": cancel_at,
        "is_referred": user.referred_by_id is not None,
        "ref_success": ref_success == "1",
        "ref_error_msg": _REFERRAL_ERROR_MESSAGES.get(ref_error),
        "hotkey_capture": hk["capture"],
        "hotkey_audio":   hk["audio"],
        "hotkey_toggle":  hk["toggle"],
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
    return {"status": "ok"}


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
                      limit_msg="Capture limit reached — you can capture up to 6 times per minute")

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

    prompt = AI_PROMPT + COMPLEXITY_SUFFIX[body.complexity]

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
    return {"status": "ok", "capture_id": capture_id}


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
                      limit_msg="Recording limit reached — you can record up to 10 times per minute")
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

        prompt = AI_PROMPT + f"\n\nThe interviewer said: {transcription_text}"
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
    except Exception as exc:
        await broadcast(r, user.id, "audio-error", {"message": str(exc)})
        raise HTTPException(status_code=500, detail="Audio processing failed")
    finally:
        os.unlink(tmp_path)

    return {"status": "ok"}


@app.get("/api/me")
async def api_me(user: User = Depends(get_user_by_token)):
    return {"account_level": user.account_level.value, "hotkeys": _user_hotkeys(user)}


@app.post("/api/settings/hotkeys")
async def save_hotkeys(data: HotkeySettings, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user.hotkey_capture = data.capture
    user.hotkey_audio   = data.audio
    user.hotkey_toggle  = data.toggle
    db.commit()
    return {"status": "ok"}


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
    return RedirectResponse(url)


@app.get("/billing/cancel")
async def billing_cancel(request: Request, user: User = Depends(get_current_user)):
    hk = _user_hotkeys(user)
    return templates.TemplateResponse(request=request, name="cancel_confirm.html", context={
        "hotkey_capture": hk["capture"],
        "hotkey_toggle":  hk["toggle"],
    })


@app.post("/billing/offer")
async def billing_offer(user: User = Depends(get_current_user)):
    # TODO: apply 50% coupon via Stripe before redirecting
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
async def billing_success(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
