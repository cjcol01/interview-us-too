import re
from datetime import datetime, timedelta
from typing import Optional

import bcrypt as _bcrypt
from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import SECRET_KEY
from database import get_db
from models import User

import secrets as _secrets


def generate_unique_referral_code(db: Session) -> str:
    for _ in range(10):
        code = _secrets.token_urlsafe(8)
        if not db.query(User).filter(User.referral_code == code).first():
            return code
    raise RuntimeError("Could not generate unique referral code")


def generate_unique_username(db: Session, base: str) -> str:
    """Derives a free `username` from an email local-part (or any base string) — used
    for accounts created via Google sign-in, which don't collect a username up front."""
    slug = re.sub(r"[^a-z0-9_]", "", base.lower()) or "user"
    # Keep generated names inside validate_username's bounds, so every row in the table is a
    # name its owner could also have typed themselves. A short email local-part ("jo@…") would
    # otherwise yield a username below USERNAME_MIN_LENGTH.
    slug = slug[:USERNAME_MAX_LENGTH].ljust(USERNAME_MIN_LENGTH, "0")
    # Case-insensitive uniqueness: the slug is already lowercase, but an existing username
    # differing only in case (e.g. "John") must still count as taken.
    if not db.query(User).filter(func.lower(User.username) == slug).first():
        return slug
    for _ in range(20):
        candidate = f"{slug}{_secrets.randbelow(1_000_000)}"
        if not db.query(User).filter(func.lower(User.username) == candidate).first():
            return candidate
    raise RuntimeError("Could not generate unique username")

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7
_bearer = HTTPBearer()

PASSWORD_MIN_LENGTH = 8

# Mirrors the checklist shown on the signup form (templates/login.html) — keep both in sync.
PASSWORD_RULES = [
    ("length", f"At least {PASSWORD_MIN_LENGTH} characters", lambda p: len(p) >= PASSWORD_MIN_LENGTH),
    ("uppercase", "One uppercase letter", lambda p: bool(re.search(r"[A-Z]", p))),
    ("lowercase", "One lowercase letter", lambda p: bool(re.search(r"[a-z]", p))),
    ("number", "One number", lambda p: bool(re.search(r"\d", p))),
    ("symbol", "One symbol (e.g. !?@#$%)", lambda p: bool(re.search(r"[^A-Za-z0-9]", p))),
]


def validate_password(password: str) -> Optional[str]:
    """Returns an error message for the first unmet rule, or None if the password is valid."""
    for _key, label, check in PASSWORD_RULES:
        if not check(password):
            return f"Password must include: {label.lower()}."
    return None


USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 32

# Letters, digits, and the three separators — nothing else. Crucially this excludes '@':
# /auth/login routes an identifier containing '@' to the email column and nothing else, so an
# email-shaped username would be an account nobody could ever sign into. It also excludes
# whitespace, which otherwise makes two visually identical usernames distinct rows. Leading '_'
# stays legal — the test suite namespaces its fixtures that way (tests/helpers.py). Keep in sync
# with templates/login.html and templates/settings.html.
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
USERNAME_RULE_TEXT = "Usernames can only use letters, numbers, and . - _"


def validate_username(username: str) -> Optional[str]:
    """Returns an error message if `username` isn't a legal username, or None if it is.
    Applied on registration and on username change — not on login, where the stored value is
    matched as-is (accounts predating this rule must still be able to sign in)."""
    if len(username) < USERNAME_MIN_LENGTH:
        return f"Username must be at least {USERNAME_MIN_LENGTH} characters."
    if len(username) > USERNAME_MAX_LENGTH:
        return f"Username must be {USERNAME_MAX_LENGTH} characters or fewer."
    if not USERNAME_RE.match(username):
        return USERNAME_RULE_TEXT
    return None


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def decode_user_id(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except Exception:
        return None


def get_optional_user(
    request: Request,
    session: Optional[str] = Cookie(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    user = None
    if session:
        try:
            payload = jwt.decode(session, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = int(payload["sub"])
            user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        except (JWTError, KeyError, ValueError):
            user = None
    # Cached so the Jinja2 context processor can reuse it without another query.
    request.state.user = user
    return user


def get_current_user(user: Optional[User] = Depends(get_optional_user)) -> User:
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def get_user_by_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    user = db.query(User).filter(
        User.api_token == credentials.credentials,
        User.is_active == True,
    ).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API token")
    return user
