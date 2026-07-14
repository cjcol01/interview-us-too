from datetime import datetime, timedelta
from typing import Optional

import bcrypt as _bcrypt
from fastapi import Cookie, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
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

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7
_bearer = HTTPBearer()


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
