import os
from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import Header, HTTPException
from jose import jwt, JWTError
from passlib.context import CryptContext


class User:
    def __init__(self, company: str, is_admin: bool = False):
        self.company = company
        self.is_admin = is_admin


# Load admin credentials from environment (seed)
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
JWT_ALGO = "HS256"
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "adminpass")

# Simple in-memory demo users (company -> password)
# In production, replace with secure user store
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# Raw user store with plaintext for initial seeding; will be hashed into _USER_STORE
_USER_STORE_RAW = {
    ADMIN_USERNAME: {"password": ADMIN_PASSWORD, "company": "admin", "is_admin": True},
    "이지메디컴": {"password": "demo", "company": "이지메디컴", "is_admin": False},
}


def _hash_store(raw):
    out = {}
    for u, info in raw.items():
        out[u] = info.copy()
        pw = info.get("password", "")
        try:
            pw_bytes = pw.encode("utf-8") if isinstance(pw, str) else pw
            if isinstance(pw_bytes, (bytes, bytearray)) and len(pw_bytes) > 72:
                pw = pw_bytes[:72].decode("utf-8", errors="ignore")
        except Exception:
            pw = pw[:72]
        out[u]["password"] = pwd_context.hash(pw)
    return out


_USER_STORE = _hash_store(_USER_STORE_RAW)


def create_access_token(username: str, is_admin: bool, expires_minutes: int = 60):
    to_encode = {"sub": username, "is_admin": is_admin}
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(username: str, password: str):
    u = _USER_STORE.get(username)
    if not u:
        return None
    if not verify_password(password, u.get("password")):
        return None
    return u


def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="인증 필요")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        username = payload.get("sub")
        is_admin = payload.get("is_admin", False)
        if username is None:
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰")
        # Map username -> company via store (demo)
        u = _USER_STORE.get(username)
        company = u.get("company") if u else username
        return User(company, is_admin)
    except JWTError:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰")
