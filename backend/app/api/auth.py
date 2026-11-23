import hmac

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import auth
from ..config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Login(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: Login, request: Request, response: Response) -> dict[str, str]:
    ip = request.client.host if request.client else "?"
    if auth.throttled(ip):
        raise HTTPException(429, "too many attempts, try later")
    if not settings.auth_password_hash:
        raise HTTPException(503, "AUTH_PASSWORD_HASH is not configured (run python -m app.hashpw)")
    ok_user = hmac.compare_digest(body.username, settings.auth_username)
    ok_pw = auth.verify_password(body.password, settings.auth_password_hash)
    if not (ok_user and ok_pw):
        auth.record_fail(ip)
        raise HTTPException(401, "invalid credentials")
    response.set_cookie(auth.COOKIE, auth.make_token(body.username), httponly=True,
                        samesite="lax", max_age=settings.session_hours * 3600)
    return {"user": body.username}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: str = Depends(auth.require_user)) -> dict[str, str]:
    return {"user": user}
