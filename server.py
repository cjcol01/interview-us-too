import asyncio
import base64
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import anthropic
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import create_token, get_current_user, get_optional_user, get_user_by_token, hash_password, verify_password
from billing import create_checkout_session, create_portal_session, handle_webhook_event
from config import AI_PROMPT, ANTHROPIC_API_KEY, BASE_URL, SERVER_HOST, SERVER_PORT
from mailer import send_verification_email
from database import get_db, init_db
from models import AccountLevel, InterviewSession, User

templates = Jinja2Templates(directory="templates")
SCREENSHOTS_DIR = Path("screenshots")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    SCREENSHOTS_DIR.mkdir(exist_ok=True)
    print(f"[ready] http://localhost:{SERVER_PORT}")
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SESSION_DURATION = timedelta(hours=2, minutes=30)
TRIAL_DURATION   = timedelta(minutes=10)

COMPLEXITY_MIN = 1
COMPLEXITY_MAX = 3
COMPLEXITY_SUFFIX = {
    1: "\n\nComplexity level: 1/3 — give the naive approach. Simple, readable code that works but is not optimised. Brief explanation.",
    2: "\n\nComplexity level: 2/3 — give the approach a skilled but junior developer would write. Reasonably efficient, clean code with a short explanation of the reasoning.",
    3: "\n\nComplexity level: 3/3 — give the optimal approach. Best time/space complexity, clean production-quality code, with a thorough explanation including trade-offs and edge cases.",
}


@dataclass
class UserSettings:
    complexity: int = 2


# Per-user state — keyed by user.id
_subscribers:    dict[int, list[asyncio.Queue]] = {}
_capture_states: dict[int, dict]                = {}
_settings:       dict[int, UserSettings]        = {}


def _capture_state(user_id: int) -> dict:
    if user_id not in _capture_states:
        _capture_states[user_id] = {"analysis": "", "timestamp": "", "capture_id": 0, "monitor": ""}
    return _capture_states[user_id]


def _user_settings(user_id: int) -> UserSettings:
    if user_id not in _settings:
        _settings[user_id] = UserSettings()
    return _settings[user_id]


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


def _screenshot_path(user_id: int) -> Path:
    return SCREENSHOTS_DIR / f"{user_id}.png"


def require_subscription(user: User = Depends(get_current_user)) -> User:
    if user.account_level == AccountLevel.free:
        raise HTTPException(status_code=403, detail="Subscription required")
    return user


async def broadcast(user_id: int, event_type: str, data: dict):
    payload = json.dumps({"type": event_type, **data})
    for q in _subscribers.get(user_id, []):
        await q.put(payload)


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
async def login_page(user: Optional[User] = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/app")
    return HTMLResponse(Path("templates/login.html").read_text(encoding="utf-8"))


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
async def auth_register(body: RegisterRequest, db: Session = Depends(get_db)):
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

    verify_token = secrets.token_urlsafe(32)
    user.verify_token = verify_token
    db.commit()
    send_verification_email(user.email, verify_token)

    token = create_token(user.id)
    response = JSONResponse({"status": "ok", "username": user.username})
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
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
async def index(user: Optional[User] = Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login")
    if not user.email_verified:
        return RedirectResponse("/verify-pending")
    if user.account_level == AccountLevel.free:
        return RedirectResponse("/pricing")
    if user.account_level == AccountLevel.trial and not user.setup_complete:
        return RedirectResponse("/onboarding")
    return HTMLResponse(Path("templates/index.html").read_text(encoding="utf-8"))


@app.get("/onboarding")
async def onboarding_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login")
    if not user.email_verified:
        return RedirectResponse("/verify-pending")
    if user.account_level != AccountLevel.trial:
        return RedirectResponse("/app")
    if not user.api_token:
        user.api_token = secrets.token_urlsafe(32)
        db.commit()
    return templates.TemplateResponse(request=request, name="onboarding.html", context={
        "api_token": user.api_token,
        "base_url": BASE_URL,
    })


@app.get("/verify-pending")
async def verify_pending(request: Request, user: Optional[User] = Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login")
    if user.email_verified:
        return RedirectResponse("/app")
    return templates.TemplateResponse(request=request, name="verify_pending.html", context={
        "email": user.email,
    })


@app.get("/trial-end")
async def trial_end(user: Optional[User] = Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login")
    return HTMLResponse(Path("templates/trial_end.html").read_text(encoding="utf-8"))


@app.get("/pricing")
async def pricing_page(user: Optional[User] = Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login")
    return HTMLResponse(Path("templates/pricing.html").read_text(encoding="utf-8"))


@app.get("/settings")
async def settings_page(
    request: Request,
    user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    if not user:
        return RedirectResponse("/login")
    if not user.api_token:
        user.api_token = secrets.token_urlsafe(32)
        db.commit()
    return templates.TemplateResponse(request=request, name="settings.html", context={
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "account_level": user.account_level.value.capitalize(),
        "api_token": user.api_token,
        "base_url": BASE_URL,
    })


@app.get("/latest")
async def get_latest(user: User = Depends(require_subscription)):
    return {"capture": _capture_state(user.id), "settings": asdict(_user_settings(user.id))}


@app.get("/screenshot")
async def get_screenshot(user: User = Depends(require_subscription)):
    path = _screenshot_path(user.id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="No screenshot yet")
    return FileResponse(path, media_type="image/png")


@app.post("/settings/complexity/{direction}")
async def change_complexity(direction: str, user: User = Depends(require_subscription)):
    s = _user_settings(user.id)
    if direction == "up":
        s.complexity = min(COMPLEXITY_MAX, s.complexity + 1)
    elif direction == "down":
        s.complexity = max(COMPLEXITY_MIN, s.complexity - 1)
    await broadcast(user.id, "settings", asdict(s))
    return asdict(s)


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
        return {"is_trial": True, "started": False, "seconds_remaining": 0}
    now = datetime.utcnow()
    remaining = max(0, (session.expires_at - now).total_seconds())
    return {
        "is_trial": True,
        "started": True,
        "seconds_remaining": int(remaining),
        "expired": remaining == 0,
    }


@app.post("/api/capture")
async def api_capture(body: CaptureRequest, user: User = Depends(get_user_by_token), db: Session = Depends(get_db)):
    if user.account_level == AccountLevel.free:
        raise HTTPException(status_code=403, detail="Subscription required")
    if user.account_level == AccountLevel.trial:
        now = datetime.utcnow()
        session = db.query(InterviewSession).filter(
            InterviewSession.user_id == user.id,
            InterviewSession.expires_at > now,
            InterviewSession.ended_at == None,  # noqa: E711
        ).first()
        if not session:
            await broadcast(user.id, "trial_expired", {})
            raise HTTPException(status_code=403, detail="trial_expired")
    elif user.account_level != AccountLevel.unlimited:
        _get_or_create_session(db, user.id)
    img_b64 = body.image
    if "," in img_b64:
        img_b64 = img_b64.split(",", 1)[1]

    _screenshot_path(user.id).write_bytes(base64.b64decode(img_b64))

    state = _capture_state(user.id)
    state["capture_id"] += 1
    state["monitor"] = body.monitor
    await broadcast(user.id, "working", {"capture_id": state["capture_id"], "monitor": body.monitor})

    prompt = AI_PROMPT + COMPLEXITY_SUFFIX[body.complexity]

    response = await asyncio.to_thread(
        client.messages.create,
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )

    state["analysis"] = response.content[0].text
    state["timestamp"] = time.strftime("%H:%M:%S")

    await broadcast(user.id, "capture", state)
    return {"status": "ok", "capture_id": state["capture_id"]}


@app.get("/api/me")
async def api_me(user: User = Depends(get_user_by_token)):
    return {"account_level": user.account_level.value}


@app.post("/api/notify/disabled")
async def notify_disabled(user: User = Depends(get_user_by_token)):
    if user.account_level in (AccountLevel.free, AccountLevel.unlimited):
        return {"status": "ok"}
    await broadcast(user.id, "disabled", {})
    return {"status": "ok"}


@app.post("/api/notify/enabled")
async def notify_enabled(user: User = Depends(get_user_by_token)):
    if user.account_level in (AccountLevel.free, AccountLevel.unlimited):
        return {"status": "ok"}
    await broadcast(user.id, "enabled", {})
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
    url = create_checkout_session(user, db, plan=plan)
    return RedirectResponse(url)


@app.get("/billing/portal")
async def billing_portal(user: User = Depends(get_current_user)):
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found.")
    url = create_portal_session(user)
    return RedirectResponse(url)


@app.get("/billing/success")
async def billing_success():
    return HTMLResponse("""
        <html><head><meta http-equiv="refresh" content="2;url=/settings"></head>
        <body style="background:#0d0d0d;color:#4caf50;font-family:system-ui;display:flex;align-items:center;
        justify-content:center;height:100vh;font-size:1.1rem;">
        Payment successful! Redirecting...</body></html>
    """)


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
async def stream(user: User = Depends(require_subscription)):
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(user.id, []).append(q)

    state = _capture_state(user.id)
    s = _user_settings(user.id)

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'capture', **state})}\n\n"
            yield f"data: {json.dumps({'type': 'settings', **asdict(s)})}\n\n"
            while True:
                data = await q.get()
                yield f"data: {data}\n\n"
        finally:
            _subscribers[user.id].remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
