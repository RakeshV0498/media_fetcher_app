from __future__ import annotations

import time
from collections import defaultdict

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import settings

COOKIE = "mf_session"
_ph = PasswordHasher()
_fails: dict[str, list[float]] = defaultdict(list)
MAX_FAILS, WINDOW = 5, 600


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.app_secret, salt="session")


def make_token(user: str) -> str:
    return _serializer().dumps({"u": user})


def read_token(token: str) -> str | None:
    try:
        return _serializer().loads(token, max_age=settings.session_hours * 3600)["u"]
    except (BadSignature, KeyError):
        return None


def throttled(ip: str) -> bool:
    now = time.time()
    _fails[ip] = [t for t in _fails[ip] if now - t < WINDOW]
    return len(_fails[ip]) >= MAX_FAILS


def record_fail(ip: str) -> None:
    _fails[ip].append(time.time())


def require_user(request: Request) -> str:
    token = request.cookies.get(COOKIE)
    user = read_token(token) if token else None
    if not user:
        raise HTTPException(401, "not authenticated")
    return user
