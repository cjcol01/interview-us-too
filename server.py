import asyncio
import base64
import json
import os
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
import keyboard
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import create_token, get_current_user, get_optional_user, hash_password, verify_password
from capture import SCREENSHOT_PATH, screenshot
from config import (
    AI_PROMPT, ANTHROPIC_API_KEY,
    HOTKEY_COMPLEXITY_DOWN, HOTKEY_COMPLEXITY_UP,
    HOTKEY_LEFT, HOTKEY_RIGHT,
    SERVER_HOST, SERVER_PORT,
)
from billing import create_checkout_session, create_portal_session, handle_webhook_event
from database import get_db, init_db
from models import AccountLevel, User

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    init_db()
    _loop = asyncio.get_event_loop()
    keyboard.add_hotkey(HOTKEY_LEFT, _make_capture_handler(1), suppress=True)
    keyboard.add_hotkey(HOTKEY_RIGHT, _make_capture_handler(2), suppress=True)
    keyboard.add_hotkey(HOTKEY_COMPLEXITY_UP, lambda: adjust_complexity(1), suppress=True)
    keyboard.add_hotkey(HOTKEY_COMPLEXITY_DOWN, lambda: adjust_complexity(-1), suppress=True)
    print(f"[ready] {HOTKEY_LEFT}=left  {HOTKEY_RIGHT}=right")
    print(f"[ready] {HOTKEY_COMPLEXITY_UP}=complexity+  {HOTKEY_COMPLEXITY_DOWN}=complexity-")
    print(f"[ready] open on phone: http://<your-pc-ip>:{SERVER_PORT}")
    yield


app = FastAPI(lifespan=lifespan)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

COMPLEXITY_MIN = 1
COMPLEXITY_MAX = 3
COMPLEXITY_SUFFIX = {
    1: "\n\nComplexity level: 1/3 — give the naive approach. Simple, readable code that works but is not optimised. Brief explanation.",
    2: "\n\nComplexity level: 2/3 — give the approach a skilled but junior developer would write. Reasonably efficient, clean code with a short explanation of the reasoning.",
    3: "\n\nComplexity level: 3/3 — give the optimal approach. Best time/space complexity, clean production-quality code, with a thorough explanation including trade-offs and edge cases.",
}


@dataclass
class AppSettings:
    complexity: int = 2


settings = AppSettings()
capture_state = {"analysis": "", "timestamp": "", "capture_id": 0, "monitor": ""}
subscribers: list[asyncio.Queue] = []
_loop: asyncio.AbstractEventLoop | None = None


# ---------------------------------------------------------------------------
# Auth schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    full_name: str
    username: str
    email: str
    password: str


# ---------------------------------------------------------------------------
# Core capture logic
# ---------------------------------------------------------------------------

async def broadcast(event_type: str, data: dict):
    payload = json.dumps({"type": event_type, **data})
    for q in subscribers:
        await q.put(payload)


async def capture_and_analyze(monitor_index: int):
    loop = asyncio.get_event_loop()
    img_bytes = await loop.run_in_executor(None, lambda: screenshot(monitor_index))
    img_b64 = base64.standard_b64encode(img_bytes).decode()

    prompt = AI_PROMPT + COMPLEXITY_SUFFIX[settings.complexity]

    response = await loop.run_in_executor(
        None,
        lambda: client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        ),
    )

    capture_state["analysis"] = response.content[0].text
    capture_state["timestamp"] = time.strftime("%H:%M:%S")
    capture_state["capture_id"] += 1
    capture_state["monitor"] = "left" if monitor_index == 1 else "right"

    await broadcast("capture", capture_state)


def adjust_complexity(delta: int):
    settings.complexity = max(COMPLEXITY_MIN, min(COMPLEXITY_MAX, settings.complexity + delta))
    print(f"[complexity] {settings.complexity}")
    if _loop:
        asyncio.run_coroutine_threadsafe(broadcast("settings", asdict(settings)), _loop)


def _make_capture_handler(monitor_index: int):
    def handler():
        if _loop:
            asyncio.run_coroutine_threadsafe(capture_and_analyze(monitor_index), _loop)
    return handler


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.get("/login")
async def login_page(user: Optional[User] = Depends(get_optional_user)):
    if user:
        return RedirectResponse("/")
    return HTMLResponse(Path("templates/login.html").read_text())


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

    token = create_token(user.id)
    response = JSONResponse({"status": "ok", "username": user.username})
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 7)
    return response


@app.post("/auth/logout")
async def auth_logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session")
    return response


# ---------------------------------------------------------------------------
# Protected app routes
# ---------------------------------------------------------------------------

@app.get("/")
async def landing():
    return HTMLResponse(Path("templates/landing.html").read_text())


@app.get("/app")
async def index(user: Optional[User] = Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login")
    return HTMLResponse(Path("templates/index.html").read_text())


@app.get("/settings")
async def settings_page(request: Request, user: Optional[User] = Depends(get_optional_user)):
    if not user:
        return RedirectResponse("/login")
    return templates.TemplateResponse(request=request, name="settings.html", context={
        "full_name": user.full_name,
        "username": user.username,
        "email": user.email,
        "account_level": user.account_level.value.capitalize(),
    })


@app.get("/screenshot")
async def get_screenshot(user: User = Depends(get_current_user)):
    if not os.path.exists(SCREENSHOT_PATH):
        return HTMLResponse("not ready", status_code=404)
    return FileResponse(SCREENSHOT_PATH, media_type="image/png")


@app.get("/latest")
async def get_latest(user: User = Depends(get_current_user)):
    return {"capture": capture_state, "settings": asdict(settings)}


@app.post("/settings/complexity/{direction}")
async def change_complexity(direction: str, user: User = Depends(get_current_user)):
    if direction == "up":
        adjust_complexity(1)
    elif direction == "down":
        adjust_complexity(-1)
    return asdict(settings)


# ---------------------------------------------------------------------------
# Billing routes
# ---------------------------------------------------------------------------

@app.get("/billing/checkout")
async def billing_checkout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    url = create_checkout_session(user, db)
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


@app.get("/stream")
async def stream(user: User = Depends(get_current_user)):
    q: asyncio.Queue = asyncio.Queue()
    subscribers.append(q)

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'capture', **capture_state})}\n\n"
            yield f"data: {json.dumps({'type': 'settings', **asdict(settings)})}\n\n"
            while True:
                data = await q.get()
                yield f"data: {data}\n\n"
        finally:
            subscribers.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
